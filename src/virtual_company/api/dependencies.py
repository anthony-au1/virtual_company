"""FastAPI dependencies for application services."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.session import get_session
from virtual_company.llm import LLMProvider, LLMRegistry, LLMRole
from virtual_company.services import (
    CampaignService,
    CompanyService,
    EvidenceService,
    ResearchService,
)
from virtual_company.tools import UnavailableWebSearchTool, WebSearchTool
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
    return LLMRegistry().for_role(LLMRole.RESEARCH)


def get_web_search_tool() -> WebSearchTool:
    """Return the configured web search tool placeholder for this first slice."""
    return UnavailableWebSearchTool()


def get_research_workflow(session: SessionDependency) -> ResearchWorkflow:
    """Build a request-scoped research workflow with its dependencies."""
    return ResearchWorkflow(
        campaigns=CampaignService(session),
        research=ResearchService(session),
        llm=get_llm_provider(),
        web_search=get_web_search_tool(),
    )
