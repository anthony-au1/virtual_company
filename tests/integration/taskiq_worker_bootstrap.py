"""Deterministic provider bootstrap loaded only by failure-path worker tests."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

from virtual_company.llm.base import LLMRateLimitError
from virtual_company.services.exploration_evidence_extractor import (
    ExplorationEvidenceExtractor,
)
from virtual_company.services.exploration_fact_extractor import (
    ExplorationFactExtractor,
)
from virtual_company.services.exploration_fetch import ExplorationFetchService
from virtual_company.services.exploration_hypothesis_generator import (
    ExplorationHypothesisGenerator,
)
from virtual_company.services.exploration_query_generator import (
    ExplorationQueryGenerator,
)
from virtual_company.services.exploration_search import ExplorationSearchService
from virtual_company.task_queue import tasks
from virtual_company.tools.web_fetch import WebPage
from virtual_company.tools.web_search import SearchResponse, SearchResult
from virtual_company.workflows.exploration import graph
from virtual_company.workflows.exploration.graph import ExplorationWorkflow
from virtual_company.workflows.research import graph as research_graph
from virtual_company.workflows.research.graph import ResearchWorkflow


def _append_marker(name: str, value: str = "") -> None:
    directory = Path(os.environ["PHASE3_WORKER_MARKER_DIR"])
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / name).open("a", encoding="utf-8") as marker:
        marker.write(f"{value}\n")


class _LLMProvider:
    provider = "phase3-deterministic"
    model = "failure-path-test"

    def __init__(self) -> None:
        self.query_calls = 0

    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_model: Any
    ) -> dict[str, Any]:
        del system_prompt
        response_name = response_model.__name__
        _append_marker("provider-calls.txt", response_name)
        if response_name == "ExplorationQueryGenerationResult":
            self.query_calls += 1
            payload = json.loads(user_prompt)
            company_name = payload["company"]["name"]
            failed_company = os.getenv("PHASE3_WORKER_FAIL_COMPANY")
            if failed_company == company_name:
                raise LLMRateLimitError("deterministic recoverable test failure")
            block_company = os.getenv("PHASE3_WORKER_BLOCK_COMPANY")
            if block_company == company_name:
                _append_marker("provider-blocked.txt", company_name)
                release = Path(os.environ["PHASE3_WORKER_RELEASE_FILE"])
                deadline = asyncio.get_running_loop().time() + 120
                while not release.exists():
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError("test provider release barrier timed out")
                    await asyncio.sleep(0.02)
            block_call = int(os.getenv("PHASE3_WORKER_BLOCK_QUERY_CALL", "0"))
            if block_call == self.query_calls:
                _append_marker("provider-blocked.txt", company_name)
                release = Path(os.environ["PHASE3_WORKER_RELEASE_FILE"])
                deadline = asyncio.get_running_loop().time() + 120
                while not release.exists():
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError("test provider release barrier timed out")
                    await asyncio.sleep(0.02)
            if os.getenv("PHASE3_WORKER_EMPTY") == "true":
                return {"queries": []}
            return {
                "queries": [
                    {
                        "query": (
                            f"{company_name} {payload['obligation']['description']}"
                        )
                    }
                ]
            }
        if response_name == "ExtractedExplorationEvidenceItems":
            return {
                "evidence": [
                    {
                        "claim": "The company provides payment services",
                        "evidence_text": (
                            "The company provides payment services to local businesses."
                        ),
                    }
                ]
            }
        if response_name == "ExtractedExplorationFacts":
            return {
                "facts": [
                    {
                        "statement": "The company provides payment services",
                        "evidence_refs": ["E1"],
                    }
                ]
            }
        if response_name == "ExtractedExplorationHypotheses":
            return {
                "hypotheses": [
                    {
                        "statement": "The company may serve regional businesses",
                        "fact_refs": ["F1"],
                    }
                ]
            }
        raise AssertionError(f"Unexpected structured response: {response_name}")


class _SearchTool:
    provider = "phase3-deterministic"

    async def search(self, query: str, limit: int = 10) -> SearchResponse:
        assert limit >= 1
        return SearchResponse(
            results=[
                SearchResult(
                    title="Payment services",
                    url=f"https://source.example.test/{quote(query, safe='')}",
                    snippet=query,
                )
            ]
        )


class _FetchTool:
    provider = "phase3-deterministic"

    async def fetch(self, url: str) -> WebPage:
        return WebPage(
            url=url,
            title="Payment services",
            content="The company provides payment services to local businesses.",
        )


class _ResearchLLMProvider:
    provider = "phase4-deterministic"
    model = "worker-crash-test"

    async def generate_structured(self, *, system_prompt, user_prompt, response_model):
        del system_prompt, user_prompt
        name = response_model.__name__
        _append_marker("research-provider-calls.txt", name)
        if name == "GeneratedSearchQueries":
            return response_model(queries=["Crash Test Company research"])
        if name == "ExtractedCompanyIdentities":
            return response_model(
                companies=[
                    {
                        "name": "Crash Test Company",
                        "website": "https://crash-test-company.example",
                        "domain": "crash-test-company.example",
                    }
                ]
            )
        if name == "DiscoveredCompanies":
            return response_model(
                companies=[
                    {
                        "name": "Crash Test Company",
                        "domain": "crash-test-company.example",
                        "discovery_reason": "Deterministic test candidate",
                        "supporting_urls": ["https://discovery.example/company"],
                    }
                ]
            )
        if name == "CompanyPageAttribution":
            if os.getenv("PHASE4_RESEARCH_BLOCK_PROVIDER") == "true":
                _append_marker("research-provider-blocked.txt", str(os.getpid()))
                release = Path(os.environ["PHASE3_WORKER_RELEASE_FILE"])
                deadline = asyncio.get_running_loop().time() + 120
                while not release.exists():
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError("Research test provider barrier timed out")
                    await asyncio.sleep(0.02)
            return response_model(attributable=True, reason="Deterministic attribution")
        if name == "GeneratedCompanySearchQueries":
            if os.getenv("PHASE4_RESEARCH_BLOCK_PROVIDER") == "true":
                _append_marker("research-provider-blocked.txt", str(os.getpid()))
                release = Path(os.environ["PHASE3_WORKER_RELEASE_FILE"])
                deadline = asyncio.get_running_loop().time() + 120
                while not release.exists():
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError("Research test provider barrier timed out")
                    await asyncio.sleep(0.02)
            return response_model(queries=["Crash Test Company products"])
        raise AssertionError(f"Unexpected Research model: {name}")


class _ResearchSearchTool:
    provider = "phase4-deterministic"

    async def search(self, _query: str, limit: int = 10) -> SearchResponse:
        assert limit >= 1
        return SearchResponse(
            results=[
                SearchResult(
                    title="Crash Test Company",
                    url="https://discovery.example/company",
                    snippet="Crash Test Company builds software.",
                )
            ]
        )


def _configured_research_workflow(*, campaigns, research):
    provider = _ResearchLLMProvider()
    _append_marker("research-graph-started.txt", str(os.getpid()))
    return ResearchWorkflow(
        campaigns=campaigns,
        research=research,
        research_llm=provider,
        extraction_llm=provider,
        web_search=_ResearchSearchTool(),
        web_fetch=_FetchTool(),
    )


research_graph.create_configured_research_workflow = _configured_research_workflow


def _configured_test_workflow(
    *, database_session_factory, observability=None, **_kwargs
):
    provider = _LLMProvider()
    _append_marker("graph-started.txt", str(os.getpid()))
    return ExplorationWorkflow(
        session_factory=database_session_factory,
        query_generator=ExplorationQueryGenerator(provider),
        search_service=ExplorationSearchService(_SearchTool(), max_results=1),
        fetch_service=ExplorationFetchService(_FetchTool(), concurrency=1),
        evidence_extractor=ExplorationEvidenceExtractor(provider, concurrency=1),
        fact_extractor=ExplorationFactExtractor(provider, concurrency=1),
        hypothesis_generator=ExplorationHypothesisGenerator(provider),
        observability=observability,
    )


graph.create_configured_exploration_workflow = _configured_test_workflow

_schema = os.getenv("PHASE3_WORKER_SCHEMA")
if _schema:
    _create_engine = tasks.create_async_engine

    def _create_schema_engine(database_url: str, **kwargs):
        return _create_engine(database_url, **kwargs).execution_options(
            schema_translate_map={None: _schema}
        )

    tasks.create_async_engine = _create_schema_engine
