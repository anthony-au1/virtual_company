"""FastAPI dependencies for application services."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.session import get_session
from virtual_company.llm import (
    InstrumentedLLMProvider,
    LLMProvider,
    LLMRegistry,
    LLMRole,
)
from virtual_company.services import (
    CampaignService,
    CompanyService,
    EvidenceService,
    ResearchService,
)
from virtual_company.tools import (
    WebFetchTool,
    WebSearchTool,
    create_web_fetch_tool,
    create_web_search_tool,
)
from virtual_company.workflows.research import ResearchWorkflow

SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def get_campaign_service(session: SessionDependency) -> CampaignService:
    """Build a campaign service for the current request."""
    return CampaignService(session)


def get_company_service(session: SessionDependency) -> CompanyService:
    """Build a company service for the current request."""
    return CompanyService(session)


def get_evidence_service(session: SessionDependency) -> EvidenceService:
    """Build an evidence service for the current request."""
    return EvidenceService(session)


def get_research_service(session: SessionDependency) -> ResearchService:
    """Build the persistence service used by the research workflow."""
    return ResearchService(session)


def get_llm_provider() -> LLMProvider:
    """Build the configured research-role LLM provider."""
    return InstrumentedLLMProvider(LLMRegistry().for_role(LLMRole.RESEARCH))


def get_extraction_llm_provider() -> LLMProvider:
    """Build the configured extraction-role LLM provider."""
    return InstrumentedLLMProvider(LLMRegistry().for_role(LLMRole.EXTRACTION))


def get_web_search_tool() -> WebSearchTool:
    """Build the single web-search provider selected by application configuration."""
    return create_web_search_tool()


def get_web_fetch_tool() -> WebFetchTool:
    """Build the configured safe web-page fetch implementation."""
    return create_web_fetch_tool()


def get_research_workflow(session: SessionDependency) -> ResearchWorkflow:
    """Build a request-scoped research workflow with its dependencies."""
    return ResearchWorkflow(
        campaigns=CampaignService(session),
        research=ResearchService(session),
        research_llm=get_llm_provider(),
        extraction_llm=get_extraction_llm_provider(),
        web_search=get_web_search_tool(),
        web_fetch=get_web_fetch_tool(),
    )
