"""Extract grounded Exploration Evidence from fetched page batches."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from time import perf_counter
from typing import cast

from pydantic import BaseModel, ConfigDict, ValidationError

from virtual_company.config import Settings, get_settings
from virtual_company.domain.exploration.evidence import ExplorationEvidence
from virtual_company.llm import (
    InstrumentedLLMProvider,
    LLMConfigurationError,
    LLMProvider,
    LLMRegistry,
    LLMResponseError,
    LLMRole,
)
from virtual_company.observability import Observability, get_observability
from virtual_company.services.exploration_fetch import (
    ExplorationFetchBatchResult,
    ExplorationFetchOutcome,
    ExplorationFetchResult,
)
from virtual_company.utils.url_normalization import (
    normalize_fetch_url,
    sanitize_observability_url,
)
from virtual_company.workflows.exploration.models import (
    ExplorationEvidenceCompanyContext,
    ExplorationEvidenceObligationContext,
    ExtractedExplorationEvidenceItems,
)
from virtual_company.workflows.exploration.prompts import (
    EXTRACT_EXPLORATION_EVIDENCE_PROMPT,
    extract_exploration_evidence_system_prompt,
    extract_exploration_evidence_user_prompt,
)

DEFAULT_EXPLORATION_EVIDENCE_EXTRACTION_CONCURRENCY = 3
DEFAULT_EXPLORATION_EVIDENCE_MAX_EXCERPT_CHARS = 1_000
MAX_EXPLORATION_EVIDENCE_CLAIM_CHARS = 2_000


class ExplorationEvidenceExtractionOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ExplorationEvidenceExtractionFailureCategory(StrEnum):
    CONFIGURATION = "configuration"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    MALFORMED_OUTPUT = "malformed_output"
    UNEXPECTED_ERROR = "unexpected_error"


class ExplorationEvidencePageResult(BaseModel):
    """One extraction result per successful fetch association, in input order."""

    model_config = ConfigDict(extra="forbid")

    query: str
    search_result_url: str
    search_result_title: str
    search_result_snippet: str | None = None
    source_url: str
    final_url: str | None = None
    source_title: str | None = None
    outcome: ExplorationEvidenceExtractionOutcome
    evidence: list[ExplorationEvidence]
    failure_category: ExplorationEvidenceExtractionFailureCategory | None = None
    rejected_evidence_count: int = 0


class ExplorationEvidenceExtractionBatchResult(BaseModel):
    """Ordered page-association outcomes from one extraction batch."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    results: list[ExplorationEvidencePageResult]


class _PageExtraction(BaseModel):
    """Provider result shared across duplicate query associations for one URL."""

    candidates: list[dict[str, str]]
    failure_category: ExplorationEvidenceExtractionFailureCategory | None = None
    rejected_evidence_count: int = 0


class ExplorationEvidenceExtractor:
    """Extract and validate page evidence without search, fetch, or persistence."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        concurrency: int = DEFAULT_EXPLORATION_EVIDENCE_EXTRACTION_CONCURRENCY,
        max_excerpt_chars: int = DEFAULT_EXPLORATION_EVIDENCE_MAX_EXCERPT_CHARS,
        observability: Observability | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be greater than zero")
        if max_excerpt_chars < 1:
            raise ValueError("max_excerpt_chars must be greater than zero")
        self._provider = provider
        self._concurrency = concurrency
        self._max_excerpt_chars = max_excerpt_chars
        self._observability = observability or get_observability()

    async def extract(
        self,
        company: ExplorationEvidenceCompanyContext,
        obligation: ExplorationEvidenceObligationContext,
        fetch_batch: ExplorationFetchBatchResult,
    ) -> ExplorationEvidenceExtractionBatchResult:
        """Extract evidence from successful fetched pages and retain each association."""
        associations = [
            result
            for result in fetch_batch.results
            if result.outcome is ExplorationFetchOutcome.SUCCEEDED
            and result.page is not None
        ]
        groups: dict[str, list[ExplorationFetchResult]] = {}
        for association in associations:
            assert association.page is not None
            groups.setdefault(self._page_key(association.page.url), []).append(
                association
            )

        provider_name = str(getattr(self._provider, "provider", "unknown"))
        model_name = str(getattr(self._provider, "model", "unknown"))
        group_items = list(groups.items())
        metadata = {
            "capability": "exploration_evidence_extraction",
            "provider": provider_name,
            "model": model_name,
            "prompt_name": EXTRACT_EXPLORATION_EVIDENCE_PROMPT.name,
            "prompt_version": EXTRACT_EXPLORATION_EVIDENCE_PROMPT.version,
            "page_association_count": len(associations),
            "unique_page_count": len(group_items),
            "concurrency_limit": self._concurrency,
        }
        self._observability.event("exploration_evidence_extraction_started", **metadata)
        started = perf_counter()
        extracted: list[_PageExtraction | None] = [None] * len(group_items)
        queue: asyncio.Queue[tuple[int, ExplorationFetchResult]] = asyncio.Queue()
        for index, (_, pages) in enumerate(group_items):
            queue.put_nowait((index, pages[0]))

        async def worker() -> None:
            while True:
                try:
                    index, association = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    try:
                        extracted[index] = await self._extract_one(
                            company,
                            obligation,
                            association,
                            originating_query_count=len(group_items[index][1]),
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:  # noqa: BLE001 - isolate one page
                        extracted[index] = _PageExtraction(
                            candidates=[],
                            failure_category=(
                                ExplorationEvidenceExtractionFailureCategory.UNEXPECTED_ERROR
                            ),
                        )
                        assert association.page is not None
                        self._observability.event(
                            "exploration_page_evidence_extraction_failed",
                            failure_category=(
                                ExplorationEvidenceExtractionFailureCategory.UNEXPECTED_ERROR.value
                            ),
                            error_type=type(error).__name__,
                            source_url=sanitize_observability_url(association.page.url),
                            capability="exploration_evidence_extraction",
                        )
                finally:
                    queue.task_done()

        try:
            with self._observability.span(
                "exploration.evidence_extraction", **metadata
            ):
                await asyncio.gather(
                    *(worker() for _ in range(min(self._concurrency, len(group_items))))
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._observability.event(
                "exploration_evidence_extraction_batch_failed",
                duration_ms=int((perf_counter() - started) * 1000),
                error_type=type(error).__name__,
                **metadata,
            )
            raise

        group_result_by_key = {
            key: cast(_PageExtraction, extracted[index])
            for index, (key, _) in enumerate(group_items)
        }
        results = []
        for association in associations:
            assert association.page is not None
            extraction = group_result_by_key[self._page_key(association.page.url)]
            results.append(
                self._association_result(company, obligation, association, extraction)
            )
        unique_extractions = [cast(_PageExtraction, item) for item in extracted]
        succeeded = sum(item.failure_category is None for item in unique_extractions)
        evidence_count = sum(len(item.candidates) for item in unique_extractions)
        associated_evidence_count = sum(len(item.evidence) for item in results)
        rejected_count = sum(
            item.rejected_evidence_count for item in unique_extractions
        )
        no_evidence_count = sum(
            item.failure_category is None and not item.candidates
            for item in unique_extractions
        )
        self._observability.event(
            "exploration_evidence_extraction_completed",
            duration_ms=int((perf_counter() - started) * 1000),
            succeeded_unique_page_count=succeeded,
            failed_unique_page_count=len(unique_extractions) - succeeded,
            no_evidence_page_count=no_evidence_count,
            extracted_evidence_count=evidence_count,
            associated_evidence_count=associated_evidence_count,
            rejected_evidence_count=rejected_count,
            succeeded_association_count=sum(
                item.outcome is ExplorationEvidenceExtractionOutcome.SUCCEEDED
                for item in results
            ),
            failed_association_count=sum(
                item.outcome is ExplorationEvidenceExtractionOutcome.FAILED
                for item in results
            ),
            unique_llm_call_count=len(group_items),
            **metadata,
        )
        return ExplorationEvidenceExtractionBatchResult(
            provider=provider_name,
            model=model_name,
            results=results,
        )

    async def _extract_one(
        self,
        company: ExplorationEvidenceCompanyContext,
        obligation: ExplorationEvidenceObligationContext,
        association: ExplorationFetchResult,
        *,
        originating_query_count: int,
    ) -> _PageExtraction:
        page = association.page
        assert page is not None
        safe_url = sanitize_observability_url(page.url)
        metadata = {
            "capability": "exploration_evidence_extraction",
            "provider": str(getattr(self._provider, "provider", "unknown")),
            "model": str(getattr(self._provider, "model", "unknown")),
            "prompt_name": EXTRACT_EXPLORATION_EVIDENCE_PROMPT.name,
            "prompt_version": EXTRACT_EXPLORATION_EVIDENCE_PROMPT.version,
            "exploration_run_id": str(company.exploration_run_id),
            "exploration_company_id": str(company.exploration_company_id),
            "company_id": str(company.company_id),
            "exploration_obligation_id": str(obligation.exploration_obligation_id),
            "query": association.query,
            "source_url": safe_url,
            "originating_query_count": originating_query_count,
        }
        started = perf_counter()
        try:
            with self._observability.context(**metadata):
                response = await self._provider.generate_structured(
                    system_prompt=extract_exploration_evidence_system_prompt(),
                    user_prompt=extract_exploration_evidence_user_prompt(
                        company, obligation, page
                    ),
                    response_model=ExtractedExplorationEvidenceItems,
                )
            parsed = ExtractedExplorationEvidenceItems.model_validate(
                response.model_dump() if isinstance(response, BaseModel) else response
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - isolate failure to this URL
            category = self._failure_category(error)
            self._observability.event(
                "exploration_page_evidence_extraction_failed",
                duration_ms=int((perf_counter() - started) * 1000),
                failure_category=category.value,
                error_type=type(error).__name__,
                **metadata,
            )
            return _PageExtraction(candidates=[], failure_category=category)

        accepted: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        rejected = 0
        normalized_content = self._normalize_whitespace(page.content)
        for candidate in parsed.evidence:
            claim = self._normalize_whitespace(candidate.claim)
            excerpt = self._normalize_whitespace(candidate.evidence_text)
            # Validate structure and excerpt grounding only; semantic entailment
            # remains an explicit prompt responsibility rather than a heuristic.
            if (
                not claim
                or len(claim) > MAX_EXPLORATION_EVIDENCE_CLAIM_CHARS
                or not excerpt
                or len(excerpt) > self._max_excerpt_chars
                or excerpt not in normalized_content
            ):
                rejected += 1
                continue
            key = (claim, excerpt)
            if key in seen:
                rejected += 1
                continue
            seen.add(key)
            accepted.append({"claim": claim, "evidence_text": excerpt})

        self._observability.event(
            "exploration_page_evidence_extraction_succeeded",
            duration_ms=int((perf_counter() - started) * 1000),
            outcome="no_evidence" if not accepted else "evidence_found",
            extracted_evidence_count=len(accepted),
            rejected_evidence_count=rejected,
            **metadata,
        )
        return _PageExtraction(candidates=accepted, rejected_evidence_count=rejected)

    @staticmethod
    def _association_result(
        company: ExplorationEvidenceCompanyContext,
        obligation: ExplorationEvidenceObligationContext,
        association: ExplorationFetchResult,
        extraction: _PageExtraction,
    ) -> ExplorationEvidencePageResult:
        page = association.page
        assert page is not None
        evidence = [
            ExplorationEvidence(
                exploration_run_id=company.exploration_run_id,
                exploration_company_id=company.exploration_company_id,
                company_id=company.company_id,
                exploration_obligation_id=obligation.exploration_obligation_id,
                claim=item["claim"],
                supporting_excerpt=item["evidence_text"],
                query=association.query,
                search_result_url=association.search_result.url,
                search_result_title=association.search_result.title,
                search_result_snippet=association.search_result.snippet,
                source_url=page.url,
                final_url=page.final_url,
                source_title=page.title,
            )
            for item in extraction.candidates
        ]
        return ExplorationEvidencePageResult(
            query=association.query,
            search_result_url=association.search_result.url,
            search_result_title=association.search_result.title,
            search_result_snippet=association.search_result.snippet,
            source_url=page.url,
            final_url=page.final_url,
            source_title=page.title,
            outcome=(
                ExplorationEvidenceExtractionOutcome.FAILED
                if extraction.failure_category is not None
                else ExplorationEvidenceExtractionOutcome.SUCCEEDED
            ),
            evidence=evidence,
            failure_category=extraction.failure_category,
            rejected_evidence_count=extraction.rejected_evidence_count,
        )

    @staticmethod
    def _normalize_whitespace(value: str) -> str:
        return " ".join(value.split())

    @staticmethod
    def _page_key(url: str) -> str:
        try:
            return normalize_fetch_url(url)
        except ValueError:
            return url.strip()

    @staticmethod
    def _failure_category(
        error: Exception,
    ) -> ExplorationEvidenceExtractionFailureCategory:
        if isinstance(error, LLMConfigurationError):
            return ExplorationEvidenceExtractionFailureCategory.CONFIGURATION
        if isinstance(error, (TimeoutError, asyncio.TimeoutError)) or type(
            error
        ).__name__ in {
            "APITimeoutError",
            "ConnectTimeout",
            "ReadTimeout",
        }:
            return ExplorationEvidenceExtractionFailureCategory.TIMEOUT
        if isinstance(
            error, (LLMResponseError, ValidationError, ValueError, TypeError)
        ):
            return ExplorationEvidenceExtractionFailureCategory.MALFORMED_OUTPUT
        if type(error).__module__.startswith(("openai", "anthropic")):
            return ExplorationEvidenceExtractionFailureCategory.PROVIDER_ERROR
        if isinstance(error, Exception) and type(error).__module__.startswith(
            "virtual_company.llm"
        ):
            return ExplorationEvidenceExtractionFailureCategory.PROVIDER_ERROR
        return ExplorationEvidenceExtractionFailureCategory.UNEXPECTED_ERROR


def create_configured_exploration_evidence_extractor(
    settings: Settings | None = None,
    *,
    observability: Observability | None = None,
) -> ExplorationEvidenceExtractor:
    """Build the independently configured, safely instrumented extractor."""
    resolved_settings = settings or get_settings()
    provider = LLMRegistry(resolved_settings).for_role(
        LLMRole.EXPLORATION_EVIDENCE_EXTRACTION
    )
    instrumented = InstrumentedLLMProvider(
        provider,
        observability=observability,
        capture_io=False,
        sanitize_errors=True,
    )
    return ExplorationEvidenceExtractor(
        instrumented,
        concurrency=resolved_settings.exploration_evidence_extraction_concurrency,
        max_excerpt_chars=resolved_settings.exploration_evidence_max_excerpt_chars,
        observability=observability,
    )
