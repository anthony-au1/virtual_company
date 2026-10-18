"""Offline input fixtures for future obligation-generation evaluations."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ObligationGenerationCase:
    name: str
    business_context: str
    expected_subject: str


CASES = (
    ObligationGenerationCase(
        "consulting opportunity assessment",
        "We provide cloud and software engineering consulting. For the companies "
        "selected from Research results, understand which show technology complexity, "
        "modernisation initiatives, limited internal engineering capability, or evidence "
        "of potential demand for external engineering support.",
        "technology complexity, modernisation, internal capability, and external support demand at each selected company",
    ),
    ObligationGenerationCase(
        "competitive analysis of selected companies",
        "We want to compare the selected competitors to understand each company's "
        "product positioning, capabilities, and signs of unmet customer needs.",
        "positioning, capabilities, and unmet customer needs at each selected competitor",
    ),
    ObligationGenerationCase(
        "regulatory exposure of selected companies",
        "For each company selected from our Research results, understand whether it "
        "operates in or is otherwise exposed to a regulated environment relevant to our "
        "consumer lending business objective, and whether that exposure affects demand "
        "for our service.",
        "each selected company's relevant regulated-environment exposure and its business implications",
    ),
    ObligationGenerationCase(
        "technology-modernisation opportunity",
        "Our firm delivers data-platform modernisation. For each selected company, "
        "determine whether there is evidence of legacy analytics infrastructure, active "
        "migration programs, or a need for external modernisation support.",
        "modernisation signals and support needs at each selected company",
    ),
    ObligationGenerationCase(
        "capabilities goals and constraints",
        "We build privacy-preserving identity tools for healthcare providers and want "
        "to expand into regional hospitals. Our implementation team is small and we must "
        "meet local privacy rules. For each selected hospital company, assess evidence "
        "of relevant needs, implementation fit, and constraints on adoption.",
        "needs, adoption fit, and constraints at each selected hospital company",
    ),
    ObligationGenerationCase(
        "vague irrelevant context",
        "blue window seven maybe potato",
        "no supported company-applicable investigation question; zero obligations is valid",
    ),
)
