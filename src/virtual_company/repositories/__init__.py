"""Database repositories and their input DTOs."""

from virtual_company.repositories.campaign import CampaignRepository
from virtual_company.repositories.campaign_target import CampaignTargetRepository
from virtual_company.repositories.dtos import (
    CampaignCreate,
    CampaignTargetCreate,
    CampaignTargetUpdate,
    CampaignUpdate,
    ExplorationCompanyCreate,
    ExplorationCreate,
    ExplorationEvidenceCreate,
    ExplorationFactCreate,
    ExplorationHypothesisCreate,
    ExplorationObligationCreate,
    ExplorationObligationUpdate,
    ExplorationRunCreate,
    ExplorationRunUpdate,
    ExplorationUpdate,
    ResearchCompanyCreate,
    ResearchCompanyQualificationUpsert,
    ResearchCompanyUpdate,
    ResearchEvidenceCreate,
    ResearchEvidenceUpdate,
    ResearchRunCreate,
    ResearchRunUpdate,
)
from virtual_company.repositories.exploration import ExplorationRepository
from virtual_company.repositories.exploration_company import (
    ExplorationCompanyRepository,
)
from virtual_company.repositories.exploration_evidence import (
    ExplorationEvidenceRepository,
)
from virtual_company.repositories.exploration_fact import ExplorationFactRepository
from virtual_company.repositories.exploration_hypothesis import (
    ExplorationHypothesisRepository,
)
from virtual_company.repositories.exploration_obligation import (
    ExplorationObligationRepository,
)
from virtual_company.repositories.exploration_run import ExplorationRunRepository
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
    "ExplorationCompanyCreate",
    "ExplorationCompanyRepository",
    "ExplorationCreate",
    "ExplorationEvidenceCreate",
    "ExplorationEvidenceRepository",
    "ExplorationFactCreate",
    "ExplorationFactRepository",
    "ExplorationHypothesisCreate",
    "ExplorationHypothesisRepository",
    "ExplorationObligationCreate",
    "ExplorationObligationRepository",
    "ExplorationObligationUpdate",
    "ExplorationRepository",
    "ExplorationRunCreate",
    "ExplorationRunRepository",
    "ExplorationRunUpdate",
    "ExplorationUpdate",
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
