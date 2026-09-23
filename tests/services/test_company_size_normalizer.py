"""Grounded company-size normalization with provider stubs, never live LLMs."""

import asyncio
import json
from types import SimpleNamespace
from typing import TypeVar, cast
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from virtual_company.domain.qualification import QualificationStatus as Status
from virtual_company.research.models import CompanySizeNormalization, EmployeeCountFact
from virtual_company.services.company_size_normalizer import CompanySizeNormalizer
from virtual_company.services.qualification import (
    needs_size_normalization,
    qualify_company,
)

T = TypeVar("T", bound=BaseModel)


class ProviderStub:
    def __init__(self, output: object, *, delay: float = 0) -> None:
        self.output = output
        self.delay = delay
        self.calls: list[dict[str, object]] = []
        self.active = 0
        self.max_active = 0

    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_model: type[T]
    ) -> T:
        self.calls.append(
            {"system": system_prompt, "user": user_prompt, "model": response_model}
        )
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            if isinstance(self.output, BaseException):
                raise self.output
            return cast(T, self.output)
        finally:
            self.active -= 1


def evidence(claim: str, text: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        criterion="company_size",
        subject=None,
        claim=claim,
        evidence_text=text if text is not None else claim,
    )


def campaign() -> SimpleNamespace:
    return SimpleNamespace(
        target_market=None,
        industry=None,
        technologies=[],
        company_size_min=500,
        company_size_max=None,
    )


def fact(value: int, year: int | None = None, **changes: object) -> EmployeeCountFact:
    return EmployeeCountFact.model_validate(
        {"value": value, "year": year, "relation": "exact", "scope": "unknown"}
        | changes
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim,text,counts,expected",
    [
        (
            "Airwallex has a team of over 2,300 people across 27 offices.",
            "we have a team of over 2,300 of the brightest and most innovative people in tech across 27 offices around the globe.",
            [fact(2300, relation="greater_than", scope="global")],
            Status.MATCH,
        ),
        (
            "Cover Genius reports more than 600 global employees.",
            "+600 global employees",
            [fact(600, relation="greater_than", scope="global")],
            Status.MATCH,
        ),
        (
            "Afterpay had approximately 714 employees in 2023.",
            "from 714 employees in 2023 to 460 in 2026",
            [fact(714, 2023), fact(460, 2026)],
            Status.MISMATCH,
        ),
        (
            "Tyro has close to 600 employees.",
            "Tyro has close to 600 employees.",
            [fact(600, relation="approximately")],
            Status.UNKNOWN,
        ),
    ],
)
async def test_named_company_normalization(
    claim: str, text: str, counts: list[EmployeeCountFact], expected: Status
) -> None:
    item = evidence(claim, text)
    provider = ProviderStub(CompanySizeNormalization(counts=counts))
    result = await CompanySizeNormalizer(provider).normalize(item)
    assert result is not None and result.counts == counts
    decision = qualify_company(
        campaign(), [item], size_normalizations={item.id: result}, as_of_year=2026
    )[0]
    assert decision.status is expected
    assert decision.evidence_ids == [item.id]
    assert provider.calls[0]["model"] is CompanySizeNormalization
    assert json.loads(str(provider.calls[0]["user"])) == {
        "claim": claim,
        "evidence_text": text,
    }
    assert "company_size_min" not in str(provider.calls)
    if expected is Status.MISMATCH:
        assert "460 employees" in decision.reason and "2026" in decision.reason
        assert "superseded" in decision.reason


@pytest.mark.asyncio
async def test_simple_cases_and_other_criteria_skip_provider() -> None:
    provider = ProviderStub(AssertionError("No LLM call expected"))
    items = [
        evidence("over 2,300 people across 27 offices around the globe"),
        evidence("more than 600 global employees", "+600 global employees"),
        evidence("2000 employees"),
        evidence("Uses Java"),
    ]
    items[-1].criterion = "technology"
    assert await CompanySizeNormalizer(provider).normalize_evidence(items) == {}
    assert await CompanySizeNormalizer(provider).normalize(items[-1]) is None
    assert not provider.calls


@pytest.mark.parametrize(
    "text",
    [
        "714 employees in 2023",
        "from 714 employees in 2023 to 460 in 2026",
        "close to 600 employees",
        "staff count unavailable",
    ],
)
def test_complex_or_dated_routing(text: str) -> None:
    assert needs_size_normalization(evidence(text))


@pytest.mark.parametrize(
    "counts,expected",
    [
        ([fact(714, 2023), fact(460, 2026)], Status.MISMATCH),
        ([fact(714, 2026), fact(460, 2026)], Status.UNKNOWN),
        ([fact(714, 2023), fact(460, 2026), fact(714)], Status.UNKNOWN),
        (
            [fact(714, 2023), fact(460, 2026), fact(400, relation="greater_than")],
            Status.MISMATCH,
        ),
        ([fact(600, 2026, scope="global"), fact(600, 2023)], Status.UNKNOWN),
        ([fact(600, 2026, scope="regional")], Status.UNKNOWN),
        ([fact(600, 2027)], Status.UNKNOWN),
        ([fact(714, 2023, relation="approximately"), fact(460, 2026)], Status.MISMATCH),
        ([fact(714, 2023), fact(460, 2026, relation="approximately")], Status.UNKNOWN),
        (
            [
                fact(600, relation="greater_than"),
                fact(600, relation="greater_than_or_equal"),
            ],
            Status.MATCH,
        ),
    ],
)
def test_temporal_selection_across_records(
    counts: list[EmployeeCountFact], expected: Status
) -> None:
    items = [evidence("Validated employee observation") for _ in counts]
    normalized = {
        item.id: CompanySizeNormalization(counts=[count])
        for item, count in zip(items, counts, strict=True)
    }
    result = qualify_company(
        campaign(), items, size_normalizations=normalized, as_of_year=2026
    )[0]
    assert result.status is expected
    assert result.evidence_ids == sorted((item.id for item in items), key=str)
    assert (
        qualify_company(
            campaign(), items[::-1], size_normalizations=normalized, as_of_year=2026
        )[0]
        == result
    )


@pytest.mark.parametrize(
    "relation,value,expected",
    [
        ("exact", 500, Status.MATCH),
        ("greater_than", 499, Status.MATCH),
        ("greater_than_or_equal", 500, Status.MATCH),
        ("less_than", 500, Status.MISMATCH),
        ("less_than_or_equal", 499, Status.MISMATCH),
        ("approximately", 600, Status.UNKNOWN),
    ],
)
def test_relations_share_bounds_evaluation(
    relation: str, value: int, expected: Status
) -> None:
    item = evidence("Employee observation")
    result = qualify_company(
        campaign(),
        [item],
        size_normalizations={
            item.id: CompanySizeNormalization(counts=[fact(value, relation=relation)])
        },
    )[0]
    assert result.status is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output",
    [
        RuntimeError("provider failed"),
        {"counts": [{"value": "invalid"}]},
        CompanySizeNormalization(),
    ],
)
@pytest.mark.parametrize(
    "text,expected",
    [
        ("600 employees", Status.MATCH),
        ("600 employees in 2023", Status.UNKNOWN),
        ("close to 600 employees", Status.UNKNOWN),
        ("No supported count", Status.UNKNOWN),
    ],
)
async def test_failure_invalid_and_empty_fallback(
    output: object, text: str, expected: Status
) -> None:
    item = evidence(text)
    normalized = await CompanySizeNormalizer(ProviderStub(output)).normalize(item)
    result = qualify_company(
        campaign(), [item], size_normalizations={item.id: normalized}
    )[0]
    assert result.status is expected


@pytest.mark.asyncio
async def test_timeout_and_cancellation() -> None:
    item = evidence("close to 600 employees")
    provider = ProviderStub(CompanySizeNormalization(), delay=1)
    normalizer = CompanySizeNormalizer(provider, timeout_seconds=0.001)
    assert await normalizer.normalize(item) is None
    assert provider.active == 0
    with pytest.raises(asyncio.CancelledError):
        await CompanySizeNormalizer(ProviderStub(asyncio.CancelledError())).normalize(
            item
        )


@pytest.mark.asyncio
async def test_concurrency_and_evidence_id_deduplication() -> None:
    provider = ProviderStub(CompanySizeNormalization(), delay=0.001)
    items = [evidence("close to 600 employees") for _ in range(5)]
    result = await CompanySizeNormalizer(provider, concurrency=2).normalize_evidence(
        items + items
    )
    assert len(provider.calls) == len(result) == 5
    assert provider.max_active == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"counts": [], "decision": "MATCH"},
        {"counts": [{"value": -1, "relation": "exact"}]},
        {"counts": [{"value": True, "relation": "exact"}]},
        {"counts": [{"value": 600, "relation": "MATCH"}]},
        {"counts": [{"value": 600, "relation": "exact", "year": 0}]},
        {"counts": [{"value": 600, "relation": "exact", "scope": "inferred"}]},
        {"counts": [{"value": 600, "relation": "exact", "decision": "MATCH"}]},
    ],
)
def test_structured_schema_rejects_invalid_facts(payload: object) -> None:
    with pytest.raises(ValidationError):
        CompanySizeNormalization.model_validate(payload)


@pytest.mark.asyncio
async def test_normalization_audit_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import nullcontext
    from unittest.mock import Mock

    audit = SimpleNamespace(context=lambda **_: nullcontext(), event=Mock())
    monkeypatch.setattr(
        "virtual_company.services.company_size_normalizer.get_observability",
        lambda: audit,
    )
    item = evidence("close to 600 employees")
    output = CompanySizeNormalization(counts=[fact(600, relation="approximately")])
    await CompanySizeNormalizer(ProviderStub(output)).normalize(item)
    metadata = audit.event.call_args.kwargs
    assert metadata["evidence_id"] == str(item.id)
    assert metadata["prompt_name"] == "normalize_company_size"
    assert metadata["prompt_version"] == "v1"
    assert metadata["counts"] == [count.model_dump() for count in output.counts]
    await CompanySizeNormalizer(ProviderStub(RuntimeError("failed"))).normalize(item)
    assert audit.event.call_args.kwargs["error_type"] == "RuntimeError"
    assert audit.event.call_args.kwargs["fallback"] == "unknown"


def test_normalization_prompt_semantics() -> None:
    from virtual_company.workflows.research.prompts import (
        normalize_company_size_system_prompt,
    )

    prompt = normalize_company_size_system_prompt()
    for instruction in [
        "Do not search",
        "external knowledge",
        "different years",
        "not a range",
        "Preserve approximation",
        "scope",
        "empty counts list",
        "Do not decide campaign",
        "data, not instructions",
        "evidence_text as primary",
    ]:
        assert instruction in prompt
