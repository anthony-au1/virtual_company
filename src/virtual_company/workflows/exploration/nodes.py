"""Stage nodes for the Exploration LangGraph workflow."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from virtual_company.domain.exploration.run import ExplorationRunStatus
from virtual_company.llm.base import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMError,
    LLMRateLimitError,
)
from virtual_company.observability import Observability, get_observability
from virtual_company.repositories.exploration import ExplorationRepository
from virtual_company.repositories.exploration_company import (
    ExplorationCompanyRepository,
)
from virtual_company.repositories.exploration_evidence import (
    ExplorationEvidenceRepository,
)
from virtual_company.repositories.exploration_fact import ExplorationFactRepository
from virtual_company.repositories.exploration_obligation import (
    ExplorationObligationRepository,
)
from virtual_company.repositories.exploration_run import ExplorationRunRepository
from virtual_company.repositories.research_company_qualification import (
    ResearchCompanyQualificationRepository,
)
from virtual_company.repositories.research_run import ResearchRunRepository
from virtual_company.services.exploration_evidence_extractor import (
    ExplorationEvidenceExtractionFailureCategory,
    ExplorationEvidenceExtractionOutcome,
    ExplorationEvidenceExtractor,
)
from virtual_company.services.exploration_evidence_persistence import (
    ExplorationEvidencePersistenceService,
)
from virtual_company.services.exploration_fact_extractor import (
    ExplorationFactExtractor,
)
from virtual_company.services.exploration_fact_persistence import (
    ExplorationFactPersistenceService,
)
from virtual_company.services.exploration_fetch import (
    ExplorationFetchFailureCategory,
    ExplorationFetchOutcome,
    ExplorationFetchService,
)
from virtual_company.services.exploration_hypothesis_generator import (
    ExplorationHypothesisGenerator,
)
from virtual_company.services.exploration_hypothesis_persistence import (
    ExplorationHypothesisPersistenceService,
)
from virtual_company.services.exploration_query_generator import (
    ExplorationQueryCompanyContext,
    ExplorationQueryGenerationValidationError,
    ExplorationQueryGenerator,
    ExplorationQueryObligationContext,
)
from virtual_company.services.exploration_search import (
    ExplorationSearchFailureCategory,
    ExplorationSearchOutcome,
    ExplorationSearchService,
)
from virtual_company.workflows.exploration.models import (
    ExplorationEvidenceCompanyContext,
    ExplorationEvidenceObligationContext,
    ExplorationFactCompanyContext,
    ExplorationFactEvidenceInput,
    ExplorationFactExtractionOutcome,
    ExplorationHypothesisCompanyContext,
    ExplorationHypothesisFactInput,
    ExplorationHypothesisGenerationFailureCategory,
    ExplorationHypothesisGenerationOutcome,
)
from virtual_company.workflows.exploration.state import (
    ExplorationCompanySnapshot,
    ExplorationObligationSnapshot,
    ExplorationWorkflowState,
)


class ExplorationWorkflowInputError(ValueError):
    """A run's persisted input or ownership references are invalid."""


class ExplorationWorkflowFatalError(RuntimeError):
    """A fatal workflow error with a safe normalized category."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


class ExplorationNodes:
    """Delegate graph stages to existing services and repositories."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        query_generator: ExplorationQueryGenerator,
        search_service: ExplorationSearchService,
        fetch_service: ExplorationFetchService,
        evidence_extractor: ExplorationEvidenceExtractor,
        fact_extractor: ExplorationFactExtractor,
        hypothesis_generator: ExplorationHypothesisGenerator,
        observability: Observability | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._query_generator = query_generator
        self._search_service = search_service
        self._fetch_service = fetch_service
        self._evidence_extractor = evidence_extractor
        self._fact_extractor = fact_extractor
        self._hypothesis_generator = hypothesis_generator
        self._observability = observability or get_observability()

    async def load_context(
        self, state: ExplorationWorkflowState
    ) -> dict[str, object]:
        """Load and detach the run's complete immutable input snapshot."""
        run_id = state["exploration_run_id"]
        async with self._session_factory() as session:
            run = await ExplorationRunRepository(session).get_by_id(run_id)
            if run is None:
                raise ExplorationWorkflowInputError("ExplorationRun does not exist")
            if run.status != ExplorationRunStatus.RUNNING.value:
                raise ExplorationWorkflowInputError(
                    "ExplorationRun is not RUNNING after its guarded transition"
                )

            exploration = await ExplorationRepository(session).get_by_id(
                run.exploration_id
            )
            if exploration is None:
                raise ExplorationWorkflowInputError(
                    "ExplorationRun references a missing Exploration"
                )
            business_context = exploration.business_context
            if not isinstance(business_context, str) or not business_context.strip():
                raise ExplorationWorkflowInputError(
                    "Exploration Business Context is missing"
                )

            research_run = await ResearchRunRepository(session).get_by_id(
                run.research_run_id
            )
            if research_run is None or research_run.status != "COMPLETED":
                raise ExplorationWorkflowInputError(
                    "Source ResearchRun is missing or is not completed"
                )

            company_rows = await ExplorationCompanyRepository(session).list_by_run_id(
                run.id
            )
            company_ids = [item.company_id for item in company_rows]
            selected_ids = await ResearchCompanyQualificationRepository(
                session
            ).list_member_company_ids(run.research_run_id, company_ids)
            if selected_ids != set(company_ids):
                raise ExplorationWorkflowInputError(
                    "Selected companies do not match the ResearchRun snapshot"
                )

            companies: list[ExplorationCompanySnapshot] = []
            for item in company_rows:
                research_company = item.company
                if research_company is None or item.company_id != research_company.id:
                    raise ExplorationWorkflowInputError(
                        "ExplorationCompany references an invalid ResearchCompany"
                    )
                if item.exploration_run_id != run.id:
                    raise ExplorationWorkflowInputError(
                        "ExplorationCompany belongs to another run"
                    )
                companies.append(
                    ExplorationCompanySnapshot(
                        exploration_company_id=item.id,
                        research_company_id=research_company.id,
                        name=research_company.name,
                        website=research_company.website,
                        domain=research_company.domain,
                        industry=research_company.industry,
                        country=research_company.country,
                        state=research_company.state,
                        city=research_company.city,
                    )
                )

            obligation_rows = await ExplorationObligationRepository(
                session
            ).list_by_exploration_id(exploration.id)
            if any(item.exploration_id != exploration.id for item in obligation_rows):
                raise ExplorationWorkflowInputError(
                    "Obligation belongs to another Exploration"
                )
            obligations = tuple(
                ExplorationObligationSnapshot(
                    id=item.id,
                    description=item.description,
                )
                for item in obligation_rows
            )

            return {
                "exploration_id": exploration.id,
                "research_run_id": run.research_run_id,
                "business_context": business_context,
                "companies": tuple(companies),
                "obligations": obligations,
                "company_index": 0,
                "obligation_index": 0,
                "current_company": None,
                "current_obligation": None,
                "query_result": None,
                "search_result": None,
                "fetch_result": None,
                "evidence_result": None,
                "company_evidence": (),
                "fact_context": None,
                "fact_result": None,
                "company_facts": (),
                "hypothesis_context": None,
                "hypothesis_result": None,
                "evidence_persisted_count": 0,
                "facts_persisted_count": 0,
                "hypotheses_persisted_count": 0,
                "completed_company_obligation_count": 0,
                "recoverable_failure_count": 0,
                "failure_categories": (),
            }

    async def select_company(
        self, state: ExplorationWorkflowState
    ) -> dict[str, object]:
        index = state["company_index"]
        companies = state["companies"]
        if index >= len(companies):
            return {"current_company": None, "current_obligation": None}
        return {
            "current_company": companies[index],
            "obligation_index": 0,
            "current_obligation": None,
            "company_evidence": (),
            "fact_context": None,
            "fact_result": None,
            "company_facts": (),
            "hypothesis_context": None,
            "hypothesis_result": None,
        }

    async def select_obligation(
        self, state: ExplorationWorkflowState
    ) -> dict[str, object]:
        index = state["obligation_index"]
        obligations = state["obligations"]
        if index >= len(obligations):
            return {"current_obligation": None}
        return {
            "current_obligation": obligations[index],
            "query_result": None,
            "search_result": None,
            "fetch_result": None,
            "evidence_result": None,
        }

    async def generate_queries(
        self, state: ExplorationWorkflowState
    ) -> dict[str, object]:
        company = self._company(state)
        obligation = self._obligation(state)
        try:
            result = await self._query_generator.generate(
                state["business_context"],
                self._query_company(company),
                ExplorationQueryObligationContext(
                    description=obligation.description
                ),
            )
        except (LLMConfigurationError, LLMAuthenticationError) as error:
            raise ExplorationWorkflowFatalError(
                "provider_configuration_or_authentication",
                "Query Generation provider configuration or authentication failed",
            ) from error
        except (LLMError, TimeoutError, ExplorationQueryGenerationValidationError) as error:
            return self._recoverable(
                state, "query_generation", self._query_failure_category(error)
            )
        return {"query_result": result}

    async def search(self, state: ExplorationWorkflowState) -> dict[str, object]:
        result = await self._search_service.search(self._queries(state))
        updates: dict[str, object] = {"search_result": result}
        for item in result.query_results:
            if item.outcome is not ExplorationSearchOutcome.FAILED:
                continue
            category = item.error_category
            if category in {
                ExplorationSearchFailureCategory.CONFIGURATION,
                ExplorationSearchFailureCategory.AUTHENTICATION,
                ExplorationSearchFailureCategory.UNEXPECTED_ERROR,
            } or category is None:
                raise ExplorationWorkflowFatalError(
                    "provider_configuration_authentication_or_unexpected",
                    "Search reported a fatal provider failure",
                )
            self._merge_recoverable(
                state, updates, "search", category.value
            )
        return updates

    async def fetch(self, state: ExplorationWorkflowState) -> dict[str, object]:
        result = await self._fetch_service.fetch(self._search_result(state))
        updates: dict[str, object] = {"fetch_result": result}
        for item in result.results:
            if item.outcome is not ExplorationFetchOutcome.FAILED:
                continue
            category = item.failure_category
            if category in {
                ExplorationFetchFailureCategory.CONFIGURATION,
                ExplorationFetchFailureCategory.UNEXPECTED_ERROR,
            } or category is None:
                raise ExplorationWorkflowFatalError(
                    "provider_configuration_or_unexpected",
                    "Fetch reported a fatal provider failure",
                )
            self._merge_recoverable(state, updates, "fetch", category.value)
        return updates

    async def extract_evidence(
        self, state: ExplorationWorkflowState
    ) -> dict[str, object]:
        company = self._company(state)
        obligation = self._obligation(state)
        result = await self._evidence_extractor.extract(
            ExplorationEvidenceCompanyContext(
                exploration_run_id=state["exploration_run_id"],
                exploration_company_id=company.exploration_company_id,
                company_id=company.research_company_id,
                name=company.name,
                website=company.website,
                domain=company.domain,
                industry=company.industry,
                country=company.country,
                state=company.state,
                city=company.city,
            ),
            ExplorationEvidenceObligationContext(
                exploration_obligation_id=obligation.id,
                description=obligation.description,
            ),
            self._fetch_result(state),
        )
        updates: dict[str, object] = {"evidence_result": result}
        for item in result.results:
            if item.outcome is not ExplorationEvidenceExtractionOutcome.FAILED:
                continue
            category = item.failure_category
            if category in {
                ExplorationEvidenceExtractionFailureCategory.CONFIGURATION,
                ExplorationEvidenceExtractionFailureCategory.AUTHENTICATION,
                ExplorationEvidenceExtractionFailureCategory.UNEXPECTED_ERROR,
            } or category is None:
                raise ExplorationWorkflowFatalError(
                    "provider_configuration_authentication_or_unexpected",
                    "Evidence Extraction reported a fatal provider failure",
                )
            self._merge_recoverable(
                state, updates, "evidence_extraction", category.value
            )
        return updates

    async def persist_evidence(
        self, state: ExplorationWorkflowState
    ) -> dict[str, object]:
        batch = self._evidence_result(state)
        async with self._session_factory() as session, session.begin():
            result = await ExplorationEvidencePersistenceService(
                session, observability=self._observability
            ).persist(batch)
        return {
            "evidence_persisted_count": (
                state["evidence_persisted_count"] + result.persisted_count
            )
        }

    async def advance_obligation(
        self, state: ExplorationWorkflowState
    ) -> dict[str, object]:
        return {
            "obligation_index": state["obligation_index"] + 1,
            "completed_company_obligation_count": (
                state["completed_company_obligation_count"] + 1
            ),
            "current_obligation": None,
            "query_result": None,
            "search_result": None,
            "fetch_result": None,
            "evidence_result": None,
        }

    async def load_company_evidence(
        self, state: ExplorationWorkflowState
    ) -> dict[str, object]:
        company = self._company(state)
        async with self._session_factory() as session:
            rows = await ExplorationEvidenceRepository(
                session
            ).list_by_exploration_company_id(company.exploration_company_id)
            evidence = tuple(
                ExplorationFactEvidenceInput(
                    evidence_id=item.id,
                    exploration_company_id=item.exploration_company_id,
                    exploration_obligation_id=item.exploration_obligation_id,
                    claim=item.claim,
                    supporting_excerpt=item.supporting_excerpt,
                )
                for item in rows
            )
        context = ExplorationFactCompanyContext(
            exploration_company_id=company.exploration_company_id,
            company_name=company.name,
        )
        return {"company_evidence": evidence, "fact_context": context}

    async def extract_facts(
        self, state: ExplorationWorkflowState
    ) -> dict[str, object]:
        context = self._fact_context(state)
        result = await self._fact_extractor.extract(
            context, state["company_evidence"]
        )
        updates: dict[str, object] = {"fact_result": result}
        for item in result.outcomes:
            if item.outcome is not ExplorationFactExtractionOutcome.FAILED:
                continue
            category = item.failure_category
            if category is None:
                raise ExplorationWorkflowFatalError(
                    "unexpected_error", "Fact Extraction returned an unclassified failure"
                )
            if category.value in {
                "configuration",
                "authentication",
                "unexpected_error",
            }:
                raise ExplorationWorkflowFatalError(
                    category.value, "Fact Extraction reported a fatal failure"
                )
            self._merge_recoverable(
                state, updates, "fact_extraction", category.value
            )
        return updates

    async def persist_facts(
        self, state: ExplorationWorkflowState
    ) -> dict[str, object]:
        batch = self._fact_result(state)
        async with self._session_factory() as session, session.begin():
            result = await ExplorationFactPersistenceService(
                session, observability=self._observability
            ).persist(batch)
        return {
            "facts_persisted_count": (
                state["facts_persisted_count"] + result.persisted_count
            )
        }

    async def load_company_facts(
        self, state: ExplorationWorkflowState
    ) -> dict[str, object]:
        company = self._company(state)
        async with self._session_factory() as session:
            rows = await ExplorationFactRepository(
                session
            ).list_by_exploration_company_id(company.exploration_company_id)
            facts = tuple(
                ExplorationHypothesisFactInput(
                    fact_id=item.id,
                    exploration_company_id=item.exploration_company_id,
                    statement=item.statement,
                )
                for item in rows
            )
        context = ExplorationHypothesisCompanyContext(
            exploration_company_id=company.exploration_company_id,
            company_name=company.name,
        )
        return {"company_facts": facts, "hypothesis_context": context}

    async def generate_hypotheses(
        self, state: ExplorationWorkflowState
    ) -> dict[str, object]:
        result = await self._hypothesis_generator.generate(
            self._hypothesis_context(state),
            state["business_context"],
            state["company_facts"],
        )
        updates: dict[str, object] = {"hypothesis_result": result}
        if result.outcome is ExplorationHypothesisGenerationOutcome.FAILED:
            category = result.failure_category
            if category is None:
                raise ExplorationWorkflowFatalError(
                    "unexpected_error",
                    "Hypothesis Generation returned an unclassified failure",
                )
            if category in {
                ExplorationHypothesisGenerationFailureCategory.CONFIGURATION,
                ExplorationHypothesisGenerationFailureCategory.AUTHENTICATION,
                ExplorationHypothesisGenerationFailureCategory.UNEXPECTED_ERROR,
            }:
                raise ExplorationWorkflowFatalError(
                    category.value, "Hypothesis Generation reported a fatal failure"
                )
            self._merge_recoverable(
                state, updates, "hypothesis_generation", category.value
            )
        return updates

    async def persist_hypotheses(
        self, state: ExplorationWorkflowState
    ) -> dict[str, object]:
        batch = self._hypothesis_result(state)
        async with self._session_factory() as session, session.begin():
            result = await ExplorationHypothesisPersistenceService(
                session, observability=self._observability
            ).persist(batch)
        return {
            "hypotheses_persisted_count": (
                state["hypotheses_persisted_count"] + result.persisted_count
            )
        }

    async def advance_company(
        self, state: ExplorationWorkflowState
    ) -> dict[str, object]:
        return {
            "company_index": state["company_index"] + 1,
            "current_company": None,
            "current_obligation": None,
            "obligation_index": 0,
            "company_evidence": (),
            "fact_context": None,
            "fact_result": None,
            "company_facts": (),
            "hypothesis_context": None,
            "hypothesis_result": None,
        }

    async def finalize_run(
        self, state: ExplorationWorkflowState
    ) -> dict[str, object]:
        status = (
            ExplorationRunStatus.PARTIAL
            if state["recoverable_failure_count"]
            else ExplorationRunStatus.COMPLETED
        )
        async with self._session_factory() as session, session.begin():
            run = await ExplorationRunRepository(session).transition(
                state["exploration_run_id"], status
            )
            if run is None:
                raise ExplorationWorkflowInputError(
                    "ExplorationRun disappeared before finalization"
                )
        self._observability.event(
            "exploration_workflow_finalized",
            exploration_run_id=str(state["exploration_run_id"]),
            final_status=status.value,
            selected_company_count=len(state["companies"]),
            obligation_count=len(state["obligations"]),
            completed_company_obligation_count=(
                state["completed_company_obligation_count"]
            ),
            evidence_persisted_count=state["evidence_persisted_count"],
            facts_persisted_count=state["facts_persisted_count"],
            hypotheses_persisted_count=state["hypotheses_persisted_count"],
            recoverable_failure_count=state["recoverable_failure_count"],
        )
        return {"final_status": status}

    def _recoverable(
        self, state: ExplorationWorkflowState, stage: str, category: str
    ) -> dict[str, object]:
        updates: dict[str, object] = {}
        self._merge_recoverable(state, updates, stage, category)
        return updates

    def _merge_recoverable(
        self,
        state: ExplorationWorkflowState,
        updates: dict[str, object],
        stage: str,
        category: str,
    ) -> None:
        current = tuple(
            updates.get("failure_categories", state.get("failure_categories", ()))
        )
        updates["failure_categories"] = (*current, f"{stage}:{category}")
        updates["recoverable_failure_count"] = (
            updates.get(
                "recoverable_failure_count",
                state.get("recoverable_failure_count", 0),
            )
            + 1
        )
        company = state.get("current_company")
        obligation = state.get("current_obligation")
        self._observability.event(
            "exploration_workflow_scoped_failure",
            exploration_run_id=str(state["exploration_run_id"]),
            exploration_company_id=(
                str(company.exploration_company_id) if company else None
            ),
            exploration_obligation_id=str(obligation.id) if obligation else None,
            stage=stage,
            failure_category=category,
        )

    @staticmethod
    def _query_failure_category(error: Exception) -> str:
        if isinstance(error, TimeoutError):
            return "timeout"
        if isinstance(error, ExplorationQueryGenerationValidationError):
            return "malformed_output"
        if isinstance(error, LLMRateLimitError):
            return "rate_limited"
        return "provider_error"

    @staticmethod
    def _query_company(
        company: ExplorationCompanySnapshot,
    ) -> ExplorationQueryCompanyContext:
        return ExplorationQueryCompanyContext(
            name=company.name,
            website=company.website,
            domain=company.domain,
            industry=company.industry,
            country=company.country,
            state=company.state,
            city=company.city,
        )

    @staticmethod
    def _company(state: ExplorationWorkflowState) -> ExplorationCompanySnapshot:
        company = state.get("current_company")
        if company is None:
            raise ExplorationWorkflowFatalError(
                "internal_invariant", "No company is selected for this graph stage"
            )
        return company

    @staticmethod
    def _obligation(state: ExplorationWorkflowState) -> ExplorationObligationSnapshot:
        obligation = state.get("current_obligation")
        if obligation is None:
            raise ExplorationWorkflowFatalError(
                "internal_invariant", "No Obligation is selected for this graph stage"
            )
        return obligation

    @staticmethod
    def _queries(state: ExplorationWorkflowState):
        result = state.get("query_result")
        if result is None:
            raise ExplorationWorkflowFatalError(
                "internal_invariant", "Query Generation result is missing"
            )
        return result.queries

    @staticmethod
    def _search_result(state: ExplorationWorkflowState):
        result = state.get("search_result")
        if result is None:
            raise ExplorationWorkflowFatalError(
                "internal_invariant", "Search result is missing"
            )
        return result

    @staticmethod
    def _fetch_result(state: ExplorationWorkflowState):
        result = state.get("fetch_result")
        if result is None:
            raise ExplorationWorkflowFatalError(
                "internal_invariant", "Fetch result is missing"
            )
        return result

    @staticmethod
    def _evidence_result(state: ExplorationWorkflowState):
        result = state.get("evidence_result")
        if result is None:
            raise ExplorationWorkflowFatalError(
                "internal_invariant", "Evidence Extraction result is missing"
            )
        return result

    @staticmethod
    def _fact_result(state: ExplorationWorkflowState):
        result = state.get("fact_result")
        if result is None:
            raise ExplorationWorkflowFatalError(
                "internal_invariant", "Fact Extraction result is missing"
            )
        return result

    @staticmethod
    def _fact_context(state: ExplorationWorkflowState):
        context = state.get("fact_context")
        if context is None:
            raise ExplorationWorkflowFatalError(
                "internal_invariant", "Fact Extraction context is missing"
            )
        return context

    @staticmethod
    def _hypothesis_context(state: ExplorationWorkflowState):
        context = state.get("hypothesis_context")
        if context is None:
            raise ExplorationWorkflowFatalError(
                "internal_invariant", "Hypothesis Generation context is missing"
            )
        return context

    @staticmethod
    def _hypothesis_result(state: ExplorationWorkflowState):
        result = state.get("hypothesis_result")
        if result is None:
            raise ExplorationWorkflowFatalError(
                "internal_invariant", "Hypothesis Generation result is missing"
            )
        if result.outcome is not ExplorationHypothesisGenerationOutcome.SUCCEEDED:
            raise ExplorationWorkflowFatalError(
                "internal_invariant", "Failed Hypotheses cannot be persisted"
            )
        return result

