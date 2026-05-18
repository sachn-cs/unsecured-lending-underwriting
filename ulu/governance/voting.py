"""DAO vote tallying and parameter execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Vote:
    """Represents a single governance vote."""

    voter_id: str
    proposal_id: str
    weight: float
    in_favor: bool


class GovernanceTally:
    """Tallys votes and determines winning parameter updates."""

    def __init__(
        self,
        majority_threshold: float = 0.51,
        min_participation_weight: float = 0.0,
    ) -> None:
        if not (0.0 <= majority_threshold <= 1.0):
            raise ValueError("majority_threshold must be in [0, 1]")
        if min_participation_weight < 0:
            raise ValueError("min_participation_weight must be non-negative")
        self.majority_threshold = majority_threshold
        self.min_participation_weight = min_participation_weight
        self.votes: list[Vote] = []

    def cast(self, vote: Vote) -> None:
        if vote.weight <= 0:
            raise ValueError("vote weight must be positive")
        self.votes = [v for v in self.votes if not (v.voter_id == vote.voter_id and v.proposal_id == vote.proposal_id)]
        self.votes.append(vote)

    def tally(self, proposal_id: str) -> dict:
        relevant = [v for v in self.votes if v.proposal_id == proposal_id]
        total_weight = sum(v.weight for v in relevant)
        if total_weight == 0:
            return {"passed": False, "reason": "no_votes"}
        if total_weight < self.min_participation_weight:
            return {"passed": False, "reason": "quorum_not_met"}
        in_favor_weight = sum(v.weight for v in relevant if v.in_favor)
        ratio = in_favor_weight / total_weight
        return {
            "proposal_id": proposal_id,
            "total_weight": total_weight,
            "in_favor_weight": in_favor_weight,
            "ratio": ratio,
            "passed": ratio >= self.majority_threshold,
        }
