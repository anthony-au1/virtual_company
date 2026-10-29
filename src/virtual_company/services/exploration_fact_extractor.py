"""Extract validated Exploration Facts from explicitly supplied Evidence."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ValidationError

from virtual_company.config import Settings, get_settings
from virtual_company.domain.exploration.facts import ExplorationFact
from virtual_company.llm import (
    InstrumentedLLMProvider,
    LLMConfigurationError,
    LLMError,
    LLMProvider,
    LLMRegistry,
    LLMResponseError,
    LLMRole,
)
from virtual_company.observability import Observability, get_observability
from virtual_company.workflows.exploration.models import (
    ExplorationFactCompanyContext,
    ExplorationFactEvidenceInput,
    ExplorationFactExtractionBatchResult,
    ExplorationFactExtractionChunkResult,
    ExplorationFactExtractionFailureCategory,
    ExplorationFactExtractionOutcome,
    ExtractedExplorationFacts,
)
from virtual_company.workflows.exploration.prompts import (
    EXTRACT_EXPLORATION_FACTS_PROMPT,
    extract_exploration_facts_system_prompt,
    extract_exploration_facts_user_prompt,
)

DEFAULT_EXPLORATION_FACT_EXTRACTION_CONCURRENCY = 3
DEFAULT_EXPLORATION_FACT_EXTRACTION_TIMEOUT_SECONDS = 60.0
DEFAULT_EXPLORATION_FACT_EXTRACTION_MAX_EVIDENCE_PER_CHUNK = 20
DEFAULT_EXPLORATION_FACT_EXTRACTION_MAX_CHARS_PER_CHUNK = 30_000
MAX_EXPLORATION_FACT_STATEMENT_CHARS = 2_000


class ExplorationFactInputValidationError(ValueError):
    """Raised when supplied Evidence does not belong to the selected company."""


@dataclass(frozen=True)
class _EvidenceChunk:
    index: int
    evidence: tuple[ExplorationFactEvidenceInput, ...]
    input_limit: bool = False


class ExplorationFactExtractor:
    """Normalize Evidence into supported transient Facts, without persistence."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        concurrency: int = DEFAULT_EXPLORATION_FACT_EXTRACTION_CONCURRENCY,
        timeout_seconds: float = DEFAULT_EXPLORATION_FACT_EXTRACTION_TIMEOUT_SECONDS,
        max_evidence_per_chunk: int = (
            DEFAULT_EXPLORATION_FACT_EXTRACTION_MAX_EVIDENCE_PER_CHUNK
        ),
        max_chars_per_chunk: int = (
            DEFAULT_EXPLORATION_FACT_EXTRACTION_MAX_CHARS_PER_CHUNK
        ),
        observability: Observability | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be greater than zero")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if max_evidence_per_chunk < 1:
            raise ValueError("max_evidence_per_chunk must be greater than zero")
        if max_chars_per_chunk < 1:
            raise ValueError("max_chars_per_chunk must be greater than zero")
        self._provider = provider
        self._concurrency = concurrency
        self._timeout_seconds = timeout_seconds
        self._max_evidence_per_chunk = max_evidence_per_chunk
        self._max_chars_per_chunk = max_chars_per_chunk
        self._observability = observability or get_observability()

    async def extract(
        self,
        company: ExplorationFactCompanyContext,
        evidence: Sequence[ExplorationFactEvidenceInput],
    ) -> ExplorationFactExtractionBatchResult:
        """Extract Facts for one company from ordered persisted Evidence inputs."""
        for item in evidence:
            if item.exploration_company_id != company.exploration_company_id:
                raise ExplorationFactInputValidationError(
                    "All Evidence inputs must belong to the selected ExplorationCompany"
                )

        chunks = self._chunk_evidence(evidence)
        provider_name = str(getattr(self._provider, "provider", "unknown"))
        model_name = str(getattr(self._provider, "model", "unknown"))
        metadata: dict[str, str | int | float] = {
            "capability": LLMRole.EXPLORATION_FACT_EXTRACTION.value,
            "provider": provider_name,
            "model": model_name,
            "prompt_name": EXTRACT_EXPLORATION_FACTS_PROMPT.name,
            "prompt_version": EXTRACT_EXPLORATION_FACTS_PROMPT.version,
            "exploration_company_id": str(company.exploration_company_id),
            "chunk_count": len(chunks),
            "evidence_count": len(evidence),
            "concurrency_limit": self._concurrency,
        }
        self._observability.event("exploration_fact_extraction_started", **metadata)
        started = perf_counter()
        outcomes: list[ExplorationFactExtractionChunkResult | None] = [None] * len(
            chunks
        )
        queue: asyncio.Queue[_EvidenceChunk] = asyncio.Queue()
        for chunk in chunks:
            queue.put_nowait(chunk)

        async def worker() -> None:
            while True:
                try:
                    chunk = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    try:
                        outcomes[chunk.index] = await self._extract_chunk(
                            company, chunk, chunk_count=len(chunks)
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:  # noqa: BLE001 - isolate each chunk
                        category = self._failure_category(error)
                        outcomes[chunk.index] = self._failed_chunk(chunk, category)
                        self._observability.event(
                            "exploration_fact_extraction_chunk_failed",
                            chunk_index=chunk.index,
                            evidence_count=len(chunk.evidence),
                            failure_category=category.value,
                            error_type=type(error).__name__,
                            **metadata,
                        )
                finally:
                    queue.task_done()

        try:
            with (
                self._observability.context(
                    exploration_company_id=str(company.exploration_company_id)
                ),
                self._observability.span("exploration.fact_extraction", **metadata),
            ):
                worker_count = min(self._concurrency, len(chunks))
                if worker_count:
                    await asyncio.gather(*(worker() for _ in range(worker_count)))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._observability.event(
                "exploration_fact_extraction_batch_failed",
                duration_ms=int((perf_counter() - started) * 1000),
                error_type=type(error).__name__,
                **metadata,
            )
            raise

        ordered_outcomes = [
            cast(ExplorationFactExtractionChunkResult, item) for item in outcomes
        ]
        facts = self._merge_exact_duplicates(ordered_outcomes)
        succeeded_count = sum(
            item.outcome is ExplorationFactExtractionOutcome.SUCCEEDED
            for item in ordered_outcomes
        )
        rejected_count = sum(item.rejected_fact_count for item in ordered_outcomes)
        self._observability.event(
            "exploration_fact_extraction_completed",
            duration_ms=int((perf_counter() - started) * 1000),
            succeeded_chunk_count=succeeded_count,
            failed_chunk_count=len(ordered_outcomes) - succeeded_count,
            fact_count=len(facts),
            rejected_fact_count=rejected_count,
            **metadata,
        )
        return ExplorationFactExtractionBatchResult(
            exploration_company_id=company.exploration_company_id,
            provider=provider_name,
            model=model_name,
            outcomes=ordered_outcomes,
            facts=facts,
        )

    def _chunk_evidence(
        self, evidence: Sequence[ExplorationFactEvidenceInput]
    ) -> list[_EvidenceChunk]:
        chunks: list[_EvidenceChunk] = []
        current: list[ExplorationFactEvidenceInput] = []
        current_chars = 0

        def append_current() -> None:
            nonlocal current, current_chars
            if current:
                chunks.append(_EvidenceChunk(len(chunks), tuple(current)))
                current = []
                current_chars = 0

        for item in evidence:
            item_chars = len(item.claim) + len(item.supporting_excerpt)
            if item_chars > self._max_chars_per_chunk:
                append_current()
                chunks.append(_EvidenceChunk(len(chunks), (item,), input_limit=True))
                continue
            if current and (
                len(current) >= self._max_evidence_per_chunk
                or current_chars + item_chars > self._max_chars_per_chunk
            ):
                append_current()
            current.append(item)
            current_chars += item_chars
        append_current()
        return chunks

    async def _extract_chunk(
        self,
        company: ExplorationFactCompanyContext,
        chunk: _EvidenceChunk,
        *,
        chunk_count: int,
    ) -> ExplorationFactExtractionChunkResult:
        if chunk.input_limit:
            return self._failed_chunk(
                chunk, ExplorationFactExtractionFailureCategory.INPUT_LIMIT
            )

        label_to_evidence = {
            f"E{index}": item for index, item in enumerate(chunk.evidence, start=1)
        }
        labeled_evidence = [
            {
                "evidence_ref": label,
                "claim": item.claim,
                "supporting_excerpt": item.supporting_excerpt,
            }
            for label, item in label_to_evidence.items()
        ]
        metadata = {
            "capability": LLMRole.EXPLORATION_FACT_EXTRACTION.value,
            "provider": str(getattr(self._provider, "provider", "unknown")),
            "model": str(getattr(self._provider, "model", "unknown")),
            "prompt_name": EXTRACT_EXPLORATION_FACTS_PROMPT.name,
            "prompt_version": EXTRACT_EXPLORATION_FACTS_PROMPT.version,
            "exploration_company_id": str(company.exploration_company_id),
            "chunk_index": chunk.index,
            "chunk_count": chunk_count,
            "evidence_count": len(chunk.evidence),
        }
        started = perf_counter()
        try:
            async with asyncio.timeout(self._timeout_seconds):
                response = await self._provider.generate_structured(
                    system_prompt=extract_exploration_facts_system_prompt(),
                    user_prompt=extract_exploration_facts_user_prompt(
                        company.company_name, labeled_evidence
                    ),
                    response_model=ExtractedExplorationFacts,
                )
            parsed = ExtractedExplorationFacts.model_validate(
                response.model_dump() if isinstance(response, BaseModel) else response
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - report normalized chunk failure
            category = self._failure_category(error)
            self._observability.event(
                "exploration_fact_extraction_chunk_failed",
                duration_ms=int((perf_counter() - started) * 1000),
                failure_category=category.value,
                error_type=type(error).__name__,
                **metadata,
            )
            return self._failed_chunk(chunk, category)

        accepted: list[ExplorationFact] = []
        rejected_count = 0
        for candidate in parsed.facts:
            statement = re.sub(r"\s+", " ", candidate.statement).strip()
            if (
                not statement
                or len(statement) > MAX_EXPLORATION_FACT_STATEMENT_CHARS
                or not candidate.evidence_refs
                or any(
                    label not in label_to_evidence for label in candidate.evidence_refs
                )
            ):
                rejected_count += 1
                continue
            evidence_ids = tuple(
                dict.fromkeys(
                    label_to_evidence[label].evidence_id
                    for label in candidate.evidence_refs
                )
            )
            if any(
                label_to_evidence[label].exploration_company_id
                != company.exploration_company_id
                for label in candidate.evidence_refs
            ):
                rejected_count += 1
                continue
            try:
                accepted.append(
                    ExplorationFact(
                        exploration_company_id=company.exploration_company_id,
                        statement=statement,
                        evidence_ids=evidence_ids,
                    )
                )
            except (ValidationError, ValueError):
                rejected_count += 1

        result = ExplorationFactExtractionChunkResult(
            chunk_index=chunk.index,
            evidence_count=len(chunk.evidence),
            outcome=ExplorationFactExtractionOutcome.SUCCEEDED,
            facts=accepted,
            rejected_fact_count=rejected_count,
        )
        self._observability.event(
            "exploration_fact_extraction_chunk_succeeded",
            duration_ms=int((perf_counter() - started) * 1000),
            fact_count=len(accepted),
            rejected_fact_count=rejected_count,
            **metadata,
        )
        return result

    @staticmethod
    def _failed_chunk(
        chunk: _EvidenceChunk,
        category: ExplorationFactExtractionFailureCategory,
    ) -> ExplorationFactExtractionChunkResult:
        return ExplorationFactExtractionChunkResult(
            chunk_index=chunk.index,
            evidence_count=len(chunk.evidence),
            outcome=ExplorationFactExtractionOutcome.FAILED,
            failure_category=category,
        )

    @staticmethod
    def _merge_exact_duplicates(
        outcomes: list[ExplorationFactExtractionChunkResult],
    ) -> list[ExplorationFact]:
        facts: list[ExplorationFact] = []
        positions: dict[tuple[UUID, str], int] = {}
        for outcome in outcomes:
            if outcome.outcome is not ExplorationFactExtractionOutcome.SUCCEEDED:
                continue
            for fact in outcome.facts:
                key = (
                    fact.exploration_company_id,
                    " ".join(fact.statement.split()).casefold(),
                )
                position = positions.get(key)
                if position is None:
                    positions[key] = len(facts)
                    facts.append(fact)
                    continue
                current = facts[position]
                evidence_ids = tuple(
                    dict.fromkeys((*current.evidence_ids, *fact.evidence_ids))
                )
                facts[position] = current.model_copy(
                    update={"evidence_ids": evidence_ids}
                )
        return facts

    @staticmethod
    def _failure_category(
        error: Exception,
    ) -> ExplorationFactExtractionFailureCategory:
        if isinstance(error, LLMConfigurationError):
            return ExplorationFactExtractionFailureCategory.CONFIGURATION
        if isinstance(error, (TimeoutError, asyncio.TimeoutError)) or type(
            error
        ).__name__ in {"APITimeoutError", "ConnectTimeout", "ReadTimeout"}:
            return ExplorationFactExtractionFailureCategory.TIMEOUT
        if isinstance(
            error, (LLMResponseError, ValidationError, TypeError, ValueError)
        ):
            return ExplorationFactExtractionFailureCategory.MALFORMED_OUTPUT
        if isinstance(error, LLMError) or type(error).__module__.startswith(
            ("openai", "anthropic", "virtual_company.llm")
        ):
            return ExplorationFactExtractionFailureCategory.PROVIDER_ERROR
        return ExplorationFactExtractionFailureCategory.UNEXPECTED_ERROR


def create_configured_exploration_fact_extractor(
    settings: Settings | None = None,
    *,
    observability: Observability | None = None,
) -> ExplorationFactExtractor:
    """Build an independently configured, safely instrumented Fact extractor."""
    resolved_settings = settings or get_settings()
    provider = LLMRegistry(resolved_settings).for_role(
        LLMRole.EXPLORATION_FACT_EXTRACTION
    )
    instrumented = InstrumentedLLMProvider(
        provider,
        observability=observability,
        capture_io=False,
        sanitize_errors=True,
    )
    return ExplorationFactExtractor(
        instrumented,
        concurrency=resolved_settings.exploration_fact_extraction_concurrency,
        timeout_seconds=resolved_settings.exploration_fact_extraction_timeout_seconds,
        max_evidence_per_chunk=(
            resolved_settings.exploration_fact_extraction_max_evidence_per_chunk
        ),
        max_chars_per_chunk=(
            resolved_settings.exploration_fact_extraction_max_chars_per_chunk
        ),
        observability=observability,
    )
