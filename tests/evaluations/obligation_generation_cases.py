"""Offline input fixtures for future obligation-generation evaluations."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ObligationGenerationCase:
    name: str
    business_context: str
    expected_subject: str


CASES = (
    ObligationGenerationCase(
        "consulting prospect discovery",
        "We provide cloud migration consulting and want to find Australian organisations "
        "showing signs of legacy platform modernisation needs.",
        "target organisations",
    ),
    ObligationGenerationCase(
        "regulatory market entry",
        "We plan to offer a consumer lending service in Singapore and need to understand "
        "which licences and consumer protections apply.",
        "proposed lending activity and Singapore requirements",
    ),
    ObligationGenerationCase(
        "competitor and market research",
        "We are assessing the market for low-cost inventory software for independent "
        "grocery retailers in New Zealand, including competitor offerings and unmet needs.",
        "market and competitor offerings",
    ),
    ObligationGenerationCase(
        "technology-modernisation opportunity",
        "Our firm delivers data-platform modernisation. Identify organisations with "
        "evidence of legacy analytics infrastructure or an active migration program.",
        "organisations and their technology-modernisation needs",
    ),
    ObligationGenerationCase(
        "vague irrelevant context",
        "blue window seven maybe potato",
        "no supported research subject",
    ),
    ObligationGenerationCase(
        "capabilities goals and constraints",
        "We build privacy-preserving identity tools for healthcare providers. We want to "
        "expand into regional hospitals, but have a small implementation team and must "
        "meet local privacy rules. Assess demand and entry constraints.",
        "healthcare demand, implementation constraints, and applicable rules",
    ),
)
