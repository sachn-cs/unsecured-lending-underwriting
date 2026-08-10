"""The core mechanism service - owns the DelegatedUnderwriting state machine.

This service maintains the authoritative protocol state and processes all
state-transition commands. Every other service either queries this state
(via the shared store) or reacts to the domain events this service emits.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.events import Event, EventType
from underwrite.exceptions import ProtocolError
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.logger import logger
from underwrite.metrics import Collector
from underwrite.saga import Orchestrator
from underwrite.services.base import Core
from underwrite.services.mechanism.graph import DelegationGraph
from underwrite.store import Store
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.validate import PayloadValidator

EPSILON: float = 1e-12

CommandHandler = Callable[[Event], None]


class MechanismHandler(Core):
    """Maintains the delegation graph and processes all state transitions.

    Listens for service-name events (mechanism) carrying a command
    payload, e.g.::

        {'command': 'add_seed', 'user': 'bank', 'base_budget': 100000.0}

    Emits domain events like seed.added, user.added, etc.
    """

    def __init__(
        self,
        service_id: str,
        bus: EventBus,
        store: Store,
        identity: Keypair | None = None,
        metrics: Collector | None = None,
        health: Checks | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: Orchestrator | None = None,
        supervisor: Watcher | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialize the mechanism service and load persisted state."""
        super().__init__(
            service_id=service_id,
            identity=identity,
            bus=bus,
            store=store,
            metrics=metrics,
            health=health,
            authz=authz,
            tracer=tracer,
            saga=saga,
            supervisor=supervisor,
            secrets_manager=secrets_manager,
            max_concurrent=max_concurrent,
        )
        self.__graph: DelegationGraph = DelegationGraph()
        self.__command_handlers: dict[str, CommandHandler] = {
            "add_seed": self.__add_seed,
            "add_user": self.__add_user,
            "repay": self.__repay,
            "originate": self.__originate,
            "default": self.__default,
            "revoke": self.__revoke,
            "quote": self.__quote,
        }
        self.__load_store()

    @property
    def loans(self) -> dict[str, list[dict[str, Any]]]:
        """Return the loan book for testing access."""
        return self.__graph.loans

    def credit_limit(self, user: str) -> float:
        """Return the available credit limit for a user.

        Args:
            user: The user to query.

        Returns:
            Available credit limit.
        """
        return self.__graph.credit_limit(user)

    def required_delegation(self, user: str, depth: int = 0) -> float:
        """Return the minimum delegation a user must receive.

        Args:
            user: The user to query.
            depth: Current recursion depth (prevents infinite loops).

        Returns:
            Required delegation amount.
        """
        return self.__graph.required_delegation(user, depth)

    @property
    def seeds(self) -> set[str]:
        """Return a copy of the seed set."""
        with self.state_lock:
            return set(self.__graph.seeds)

    @property
    def earned(self) -> dict[str, float]:
        """Return a copy of the earned amounts dict."""
        with self.state_lock:
            return dict(self.__graph.earned)

    @property
    def principal(self) -> dict[str, float]:
        """Return a copy of the principal amounts dict."""
        with self.state_lock:
            return dict(self.__graph.principal)

    def __persist_or_rollback(self, snap: dict[str, Any]) -> None:
        """Persist state to store; roll back in-memory state on failure.

        Args:
            snap: Snapshot to restore on persistence failure.
        """
        with self.state_lock:
            serialized = self.__graph.to_dict()
            try:
                self.store.set("protocol:state", serialized)
            except (OSError, ValueError, KeyError, TypeError):
                logger.exception("failed to persist mechanism state, rolling back")
                self.__graph.restore(snap)
                raise

    def handle(self, event: Event) -> None:
        """Process a mechanism command event.

        Args:
            event: The incoming command event.
        """
        command = event.payload.get("command", "")
        handler = self.__command_handlers.get(command)
        if handler is None:
            logger.warning("unknown mechanism command: {}", command)
            return
        try:
            handler(event)
        except ProtocolError as exc:
            self.emit(
                "mechanism.rejected",
                {
                    "command": command,
                    "reason": str(exc),
                },
                correlation_id=event.correlation_id,
            )

    def __add_seed(self, event: Event) -> None:
        """Add a seed participant to the delegation graph."""
        v = PayloadValidator()
        p = event.payload
        user: str = v.non_empty(p, "user")
        budget: float = v.positive(p, "base_budget")
        with self.state_lock:
            snap = self.__graph.snapshot()
            self.__graph.add_seed(user, budget)
        self.__persist_or_rollback(snap)
        self.emit(EventType.SEED_ADDED, p, correlation_id=event.correlation_id)

    def __add_user(self, event: Event) -> None:
        """Add a downstream user sponsored by an existing participant."""
        v = PayloadValidator()
        p = event.payload
        sponsor: str = v.non_empty(p, "sponsor")
        user: str = v.non_empty(p, "user")
        amount: float = v.positive(p, "delegation_amount")
        with self.state_lock:
            snap = self.__graph.snapshot()
            self.__graph.add_user(sponsor, user, amount)
        self.__persist_or_rollback(snap)
        self.emit(EventType.USER_ADDED, p, correlation_id=event.correlation_id)

    def __repay(self, event: Event) -> None:
        """Apply a repayment and credit the user's earned amount."""
        v = PayloadValidator()
        p = event.payload
        user: str = v.non_empty(p, "user")
        delta: float = v.non_negative(p, "delta_earned")
        with self.state_lock:
            snap = self.__graph.snapshot()
            self.__graph.repay(user, delta)
        self.__persist_or_rollback(snap)
        self.emit(EventType.REPAID, p, correlation_id=event.correlation_id)

    def __originate(self, event: Event) -> None:
        """Issue a loan to a borrower."""
        v = PayloadValidator()
        p = event.payload
        borrower: str = v.non_empty(p, "borrower")
        principal: float = v.positive(p, "principal")
        term: float = v.positive(p, "term")
        dp: float = v.finite(p, "default_probability", 0.0)
        pr: float = v.finite(p, "protocol_rate", 0.0)
        mdr: float = v.finite(p, "max_delegation_rate", 0.0)
        annual_rate: float = v.finite(p, "annual_rate", pr)

        if pr < 0:
            raise ProtocolError("rates must be >= 0")
        if mdr < 0:
            raise ProtocolError("rates must be >= 0")
        if not (0.0 < dp < 1.0):
            raise ProtocolError("default probability must be in (0,1)")

        with self.state_lock:
            snap = self.__graph.snapshot()
            self.__graph.originate(borrower, principal, term, dp, pr, mdr)
        total_interest = pr * principal * term
        p["protocol_premium"] = total_interest
        p["total_interest"] = total_interest
        p["annual_rate"] = annual_rate
        self.__persist_or_rollback(snap)
        self.emit(EventType.LOAN_ORIGINATED, p, correlation_id=event.correlation_id)

    def __default(self, event: Event) -> None:
        """Process a default, propagating the loss up the chain."""
        v = PayloadValidator()
        p = event.payload.copy()
        borrower: str = v.non_empty(p, "borrower")
        with self.state_lock:
            snap = self.__graph.snapshot()
            self.__graph.default(borrower)
            p["principal"] = self.__graph.principal.get(borrower, 0.0)
        self.__persist_or_rollback(snap)
        self.emit(EventType.DEFAULT_OCCURRED, p, correlation_id=event.correlation_id)

    def __revoke(self, event: Event) -> None:
        """Change the delegation amount on a sponsor->child edge."""
        v = PayloadValidator()
        p = event.payload
        sponsor: str = v.non_empty(p, "sponsor")
        child: str = v.non_empty(p, "child")
        new_amount: float = v.non_negative(p, "new_delegation")
        with self.state_lock:
            snap = self.__graph.snapshot()
            self.__graph.revoke(sponsor, child, new_amount)
        self.__persist_or_rollback(snap)
        self.emit(EventType.REVOKED, p, correlation_id=event.correlation_id)

    def __quote(self, event: Event) -> None:
        """Compute a quick quote without modifying state."""
        v = PayloadValidator()
        p = event.payload
        borrower: str = v.non_empty(p, "borrower")
        principal: float = v.finite(p, "principal", 0.0)
        term: float = v.positive(p, "term")
        dp: float = v.finite(p, "default_probability", 0.02)
        pr: float = v.finite(p, "protocol_rate", 0.0)

        if not (0.0 < dp < 1.0):
            raise ProtocolError("default probability must be in (0,1)")
        clamped_dp: float = max(min(dp, 1.0 - EPSILON), EPSILON)
        clamped_term: float = max(term, EPSILON)
        one_minus_dp: float = max(1.0 - clamped_dp, EPSILON)
        break_even: float = min(clamped_dp / (one_minus_dp * clamped_term), 1e6)
        total_interest: float = pr * principal * term
        self.emit(
            EventType.QUOTE_CALCULATED,
            {
                "borrower": borrower,
                "principal": principal,
                "term": term,
                "default_probability": dp,
                "protocol_rate": pr,
                "protocol_premium": total_interest,
                "total_interest": total_interest,
                "break_even_rate": break_even,
            },
            correlation_id=event.correlation_id,
        )

    def __load_store(self) -> None:
        """Load the delegation graph from the shared store."""
        with self.state_lock:
            raw = self.store.get("protocol:state")
            if raw is not None:
                self.__graph = DelegationGraph.from_dict(raw)
