"""Narrow LLM normalization of validated company-size evidence."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel

from virtual_company.llm.base import LLMProvider
from virtual_company.observability import get_observability
from virtual_company.research.models import CompanySizeNormalization
from virtual_company.services.qualification import (
    EvidenceForQualification,
    needs_size_normalization,
    size_requires_semantic_interpretation,
)
from virtual_company.workflows.research.prompts import (
    NORMALIZE_COMPANY_SIZE_PROMPT,
    normalize_company_size_system_prompt,
    normalize_company_size_user_prompt,
)


class CompanySizeNormalizer:
    """Extract facts only; leave bounds and campaign decisions to Python."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        concurrency: int = 3,
        timeout_seconds: float = 30,
    ) -> None:
        self._provider = provider
        self._semaphore = asyncio.Semaphore(concurrency)
        self._timeout_seconds = timeout_seconds

    async def normalize(
        self, item: EvidenceForQualification
    ) -> CompanySizeNormalization | None:
        if item.criterion != "company_size":
            return None
        observability = get_observability()
        metadata = {
            "evidence_id": str(item.id),
            "prompt_name": NORMALIZE_COMPANY_SIZE_PROMPT.name,
            "prompt_version": NORMALIZE_COMPANY_SIZE_PROMPT.version,
        }
        with observability.context(**metadata):
            try:
                async with self._semaphore, asyncio.timeout(self._timeout_seconds):
                    response = await self._provider.generate_structured(
                        system_prompt=normalize_company_size_system_prompt(),
                        user_prompt=normalize_company_size_user_prompt(
                            item.claim, item.evidence_text
                        ),
                        response_model=CompanySizeNormalization,
                    )
                    # Validate again at the service boundary, including provider fakes.
                    result = CompanySizeNormalization.model_validate(
                        response.model_dump()
                        if isinstance(response, BaseModel)
                        else response
                    )
            except Exception as error:  # noqa: BLE001 - isolate optional normalization
                observability.event(
                    "company_size_normalization_failed",
                    error_type=type(error).__name__,
                    fallback=(
                        "unknown"
                        if size_requires_semantic_interpretation(item)
                        else "regex_if_usable"
                    ),
                    **metadata,
                )
                return None
            observability.event(
                "company_size_normalized",
                counts=[fact.model_dump() for fact in result.counts],
                outcome="normalized" if result.counts else "empty_fallback",
                **metadata,
            )
            return result

    async def normalize_evidence(
        self, evidence: Sequence[EvidenceForQualification]
    ) -> dict[UUID, CompanySizeNormalization | None]:
        items = {item.id: item for item in evidence if needs_size_normalization(item)}
        results = await asyncio.gather(
            *(self.normalize(item) for item in items.values())
        )
        return dict(zip(items, results, strict=True))
