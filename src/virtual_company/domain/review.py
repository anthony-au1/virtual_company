"""Human review decisions for researched companies."""

from enum import StrEnum


class ReviewStatus(StrEnum):
    """A user's current decision for a company within one research run."""

    UNREVIEWED = "UNREVIEWED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
