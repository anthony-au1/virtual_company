"""Database repositories and their input DTOs."""

from virtual_company.repositories.campaign import CampaignRepository
from virtual_company.repositories.campaign_target import CampaignTargetRepository
from virtual_company.repositories.dtos import (
    CampaignCreate,
    CampaignTargetCreate,
    CampaignTargetUpdate,
    CampaignUpdate,
    ResearchCompanyCreate,
    ResearchCompanyQualificationUpsert,
    ResearchCompanyUpdate,
    ResearchEvidenceCreate,
    ResearchEvidenceUpdate,
    ResearchRunCreate,
    ResearchRunUpdate,
)
from virtual_company.repositories.research_company import ResearchCompanyRepository
from virtual_company.repositories.research_company_qualification import (
    ResearchCompanyQualificationRepository,
)
from virtual_company.repositories.research_evidence import ResearchEvidenceRepository
from virtual_company.repositories.research_run import ResearchRunRepository

__all__ = [
    "CampaignCreate",
    "CampaignRepository",
    "CampaignTargetCreate",
    "CampaignTargetRepository",
    "CampaignTargetUpdate",
    "CampaignUpdate",
    "ResearchCompanyCreate",
    "ResearchCompanyQualificationRepository",
    "ResearchCompanyQualificationUpsert",
    "ResearchCompanyRepository",
    "ResearchCompanyUpdate",
    "ResearchEvidenceCreate",
    "ResearchEvidenceRepository",
    "ResearchEvidenceUpdate",
    "ResearchRunCreate",
    "ResearchRunRepository",
    "ResearchRunUpdate",
]
