"""Database repositories and their input DTOs."""

from virtual_company.repositories.campaign import CampaignRepository
from virtual_company.repositories.campaign_target import CampaignTargetRepository
from virtual_company.repositories.company import CompanyRepository
from virtual_company.repositories.company_qualification import (
    CompanyQualificationRepository,
)
from virtual_company.repositories.dtos import (
    CampaignCreate,
    CampaignTargetCreate,
    CampaignTargetUpdate,
    CampaignUpdate,
    CompanyCreate,
    CompanyQualificationUpsert,
    CompanyUpdate,
    EvidenceCreate,
    EvidenceUpdate,
    ResearchRunCreate,
    ResearchRunUpdate,
)
from virtual_company.repositories.evidence import EvidenceRepository
from virtual_company.repositories.research_run import ResearchRunRepository

__all__ = [
    "CampaignCreate",
    "CampaignRepository",
    "CampaignTargetCreate",
    "CampaignTargetRepository",
    "CampaignTargetUpdate",
    "CampaignUpdate",
    "CompanyCreate",
    "CompanyQualificationRepository",
    "CompanyQualificationUpsert",
    "CompanyRepository",
    "CompanyUpdate",
    "EvidenceCreate",
    "EvidenceRepository",
    "EvidenceUpdate",
    "ResearchRunCreate",
    "ResearchRunRepository",
    "ResearchRunUpdate",
]
