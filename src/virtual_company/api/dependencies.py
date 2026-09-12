"""FastAPI dependencies for application services."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.session import get_session
from virtual_company.services import CampaignService, CompanyService, EvidenceService

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
