"""Protocol governance — parameter management and proposals.

Maintains protocol-level parameters (protocol_rate, max_delegation_rate,
dlg_cap_ratio, ltv_ratio, min_base_budget) within defined ranges and
processes GOVERNANCE_PROPOSAL events to update them.
"""

from __future__ import annotations

from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services import NanoService
from underwrite.validate import get_finite, get_non_empty

PARAM_RANGES: dict[str, tuple[float, float]] = {
    "protocol_rate": (0.0, 1.0),
    "max_delegation_rate": (0.0, 1.0),
    "dlg_cap_ratio": (0.0, 1.0),
    "ltv_ratio": (0.0, 1.0),
    "min_base_budget": (0.0, float("inf")),
}

PARAM_DEFAULTS: dict[str, float] = {
    "protocol_rate": 0.10,
    "max_delegation_rate": 0.05,
    "dlg_cap_ratio": 0.05,
    "ltv_ratio": 0.75,
    "min_base_budget": 1000.0,
}


class GovernanceService(NanoService):
    """Manages protocol parameters and handles governance proposals."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialise the governance service with default parameter values.

        Args:
            **kwargs: Forwarded to NanoService.__init__.
        """
        super().__init__(**kwargs)
        self.__params: dict[str, float] = dict(PARAM_DEFAULTS)

    def handle(self, event: Event) -> None:
        """Process a governance proposal to update a protocol parameter.

        Validates the parameter name and value range before applying.

        Args:
            event: The incoming event. Only GOVERNANCE_PROPOSAL events are processed.
        """
        if event.event_type == EventType.GOVERNANCE_PROPOSAL:
            p = event.payload
            param: str = get_non_empty(p, "param")
            value: float = get_finite(p, "value")
            if param not in self.__params:
                return
            lo, hi = PARAM_RANGES[param]
            if not (lo <= value <= hi):
                return
            self.__params[param] = value
            self.emit(EventType.GOVERNANCE_EXECUTED, {
                "param": param,
                "value": value,
            },
                      correlation_id=event.correlation_id)

    @property
    def params(self) -> dict[str, float]:
        """Return a snapshot of all current protocol parameters."""
        return dict(self.__params)
