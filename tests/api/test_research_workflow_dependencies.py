"""Research workflow API dependency routing tests."""

from __future__ import annotations

from types import SimpleNamespace

from virtual_company.api import dependencies
from virtual_company.llm import LLMRole


def test_api_research_workflow_injects_separate_qualification_provider(
    monkeypatch,
) -> None:
    research_llm = object()
    extraction_llm = object()
    qualification_llm = object()
    captured: dict[str, object] = {}

    class WorkflowStub:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(dependencies, "CampaignService", lambda _: object())
    monkeypatch.setattr(dependencies, "ResearchService", lambda _: object())
    monkeypatch.setattr(dependencies, "get_llm_provider", lambda: research_llm)
    monkeypatch.setattr(
        dependencies, "get_extraction_llm_provider", lambda: extraction_llm
    )
    monkeypatch.setattr(
        dependencies,
        "get_qualification_fact_extraction_llm_provider",
        lambda: qualification_llm,
    )
    monkeypatch.setattr(dependencies, "get_web_search_tool", lambda: object())
    monkeypatch.setattr(dependencies, "get_web_fetch_tool", lambda: object())
    monkeypatch.setattr(dependencies, "ResearchWorkflow", WorkflowStub)

    dependencies.get_research_workflow(object())  # type: ignore[arg-type]

    assert captured["research_llm"] is research_llm
    assert captured["extraction_llm"] is extraction_llm
    assert captured["qualification_llm"] is qualification_llm


def test_worker_research_workflow_resolves_and_injects_all_three_roles(
    monkeypatch,
) -> None:
    from virtual_company.llm import LLMRegistry
    from virtual_company.workflows.research.graph import (
        create_configured_research_workflow,
    )

    providers = {
        role: SimpleNamespace(
            model=f"model-for-{role.value}",
            provider="openai",
            role=role.value,
        )
        for role in (
            LLMRole.RESEARCH,
            LLMRole.EXTRACTION,
            LLMRole.QUALIFICATION_FACT_EXTRACTION,
        )
    }
    requested_roles: list[LLMRole] = []

    def provider_for_role(self, role: LLMRole):
        requested_roles.append(role)
        return providers[role]

    monkeypatch.setattr(LLMRegistry, "for_role", provider_for_role)
    monkeypatch.setattr("virtual_company.tools.create_web_search_tool", lambda: object())
    monkeypatch.setattr("virtual_company.tools.create_web_fetch_tool", lambda: object())

    workflow = create_configured_research_workflow(
        campaigns=object(), research=object()  # type: ignore[arg-type]
    )
    nodes = workflow._nodes

    assert set(requested_roles) == set(providers)
    assert nodes._research_llm._provider is providers[LLMRole.RESEARCH]
    assert nodes._extraction_llm._provider is providers[LLMRole.EXTRACTION]
    assert (
        nodes._qualification_extractor._provider._provider
        is providers[LLMRole.QUALIFICATION_FACT_EXTRACTION]
    )
    assert (
        nodes._qualification_extractor._provider.model
        == "model-for-qualification_fact_extraction"
    )
