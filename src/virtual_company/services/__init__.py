"""Application services coordinating repository operations.

Public service exports are loaded on demand to keep independent workflows from
importing unrelated service implementations through this package namespace.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "ActiveResearchRunError": "virtual_company.services.research_results",
    "CampaignService": "virtual_company.services.campaign",
    "ExplorationQueryCompanyContext": "virtual_company.services.exploration_query_generator",
    "ExplorationQueryGenerationResult": "virtual_company.services.exploration_query_generator",
    "ExplorationQueryGenerationValidationError": "virtual_company.services.exploration_query_generator",
    "ExplorationQueryGenerator": "virtual_company.services.exploration_query_generator",
    "ExplorationQueryObligationContext": "virtual_company.services.exploration_query_generator",
    "ExplorationQuerySearchResult": "virtual_company.services.exploration_search",
    "ExplorationFetchBatchResult": "virtual_company.services.exploration_fetch",
    "ExplorationFetchFailureCategory": "virtual_company.services.exploration_fetch",
    "ExplorationFetchOutcome": "virtual_company.services.exploration_fetch",
    "ExplorationFetchResult": "virtual_company.services.exploration_fetch",
    "ExplorationFetchService": "virtual_company.services.exploration_fetch",
    "ExplorationFetchedPage": "virtual_company.services.exploration_fetch",
    "ExplorationSearchBatchResult": "virtual_company.services.exploration_search",
    "ExplorationSearchFailureCategory": "virtual_company.services.exploration_search",
    "ExplorationSearchOutcome": "virtual_company.services.exploration_search",
    "ExplorationSearchResultItem": "virtual_company.services.exploration_search",
    "ExplorationSearchService": "virtual_company.services.exploration_search",
    "ExplorationService": "virtual_company.services.exploration",
    "GeneratedExplorationQuery": "virtual_company.services.exploration_query_generator",
    "GeneratedObligation": "virtual_company.services.obligation_generator",
    "ObligationGenerationResult": "virtual_company.services.obligation_generator",
    "ObligationGenerationValidationError": "virtual_company.services.obligation_generator",
    "ObligationGenerator": "virtual_company.services.obligation_generator",
    "PersistedResearchCompanies": "virtual_company.services.research",
    "PersistedResearchEvidence": "virtual_company.services.research",
    "ReferencedResearchRunError": "virtual_company.services.research_results",
    "ResearchCompanyService": "virtual_company.services.research_company",
    "ResearchEvidenceService": "virtual_company.services.research_evidence",
    "ResearchResultsService": "virtual_company.services.research_results",
    "ResearchRunNotFoundError": "virtual_company.services.research_results",
    "ResearchService": "virtual_company.services.research",
    "create_configured_exploration_query_generator": "virtual_company.services.exploration_query_generator",
    "create_configured_exploration_fetch_service": "virtual_company.services.exploration_fetch",
    "create_configured_exploration_search_service": "virtual_company.services.exploration_search",
    "create_configured_obligation_generator": "virtual_company.services.obligation_generator",
}

__all__ = list(_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    """Load a public service when it is first requested."""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
