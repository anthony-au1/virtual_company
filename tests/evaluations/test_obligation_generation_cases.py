"""Semantic contract checks for offline Exploration evaluation fixtures."""

from obligation_generation_cases import CASES


def test_obligation_cases_cover_company_investigation_not_discovery() -> None:
    contexts = [case.business_context.casefold() for case in CASES]
    assert len(CASES) == 6
    assert all(
        "selected" in context and ("compan" in context or "competitor" in context)
        for context in contexts[:-1]
    )
    assert not any(
        phrase in context
        for context in contexts
        for phrase in ("find companies", "identify organisations", "discover prospects")
    )
    assert any("modernisation" in context for context in contexts)
    assert any("competitors" in context for context in contexts)
    assert any("regulated environment" in context for context in contexts)
    assert "zero obligations is valid" in CASES[-1].expected_subject
