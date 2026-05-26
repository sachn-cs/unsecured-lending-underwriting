"""The core mechanism service — owns the DelegatedUnderwriting state machine.

This service maintains the authoritative protocol state and processes all
state-transition commands.  Every other service either queries this state
(via the shared store) or reacts to the domain events this service emits.
"""

from __future__ import annotations

import threading
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.__exceptions__ import InfeasibleOperationError, ProtocolError
from underwrite.services import NanoService
from underwrite.validate import get_finite, get_non_empty, get_non_negative, get_positive

EPSILON: float = 1e-12


class MechanismService(NanoService):
    """Maintains the delegation graph and processes all state transitions.

    Listens for service-name events (``mechanism``) carrying a command
    payload, e.g.::

        {"command": "add_seed", "user": "bank", "base_budget": 100000.0}

    Emits domain events like ``seed.added``, ``user.added``, etc.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialise the mechanism service and restore persisted state.

        Args:
            **kwargs: Forwarded to NanoService.__init__.
        """
        super().__init__(**kwargs)
        self.__lock: threading.RLock = threading.RLock()
        self.__seeds: set[str] = set()
        self.__parent: dict[str, str] = {}
        self.__children: dict[str, list[str]] = {}
        self.__delegation: dict[tuple[str, str], float] = {}
        self.__base_budget: dict[str, float] = {}
        self.__earned: dict[str, float] = {}
        self.__principal: dict[str, float] = {}
        self.__loans: dict[str, list[dict[str, Any]]] = {}
        self.__load_store()

    # -- public property accessors (immutable views) -------------------------

    @property
    def seeds(self) -> set[str]:
        """Return a snapshot of all seed users."""
        with self.__lock:
            return set(self.__seeds)

    @property
    def earned(self) -> dict[str, float]:
        """Return a snapshot of earned (repayable) amounts per user."""
        with self.__lock:
            return dict(self.__earned)

    @property
    def principal(self) -> dict[str, float]:
        """Return a snapshot of outstanding principal per user."""
        with self.__lock:
            return dict(self.__principal)

    # -- NanoService interface -----------------------------------------------

    def handle(self, event: Event) -> None:
        """Dispatch a command event to the appropriate handler.

        Delegates to one of add_seed, add_user, repay, originate,
        default, revoke, or quote based on the payload ``command`` field.

        Args:
            event: The incoming command event.

        Raises:
            ProtocolError: Propagated to emit a ``mechanism.rejected`` event.
        """
        command = event.payload.get("command", "")
        try:
            with self.__lock:
                if command == "add_seed":
                    self.__add_seed(event)
                elif command == "add_user":
                    self.__add_user(event)
                elif command == "repay":
                    self.__repay(event)
                elif command == "originate":
                    self.__originate(event)
                elif command == "default":
                    self.__default(event)
                elif command == "revoke":
                    self.__revoke(event)
                elif command == "quote":
                    self.__quote(event)
        except ProtocolError as exc:
            self.emit("mechanism.rejected", {
                "command": command,
                "reason": str(exc),
            },
                      correlation_id=event.correlation_id)

    # -- command handlers (all private) --------------------------------------

    def __require_user(self, user: str) -> None:
        """Raise ProtocolError if *user* is not a known participant."""
        if user not in self.__earned:
            raise ProtocolError(f"unknown user: {user}")

    def credit_limit(self, user: str) -> float:
        """Return the available credit limit for *user*."""
        with self.__lock:
            budget = self.__base_budget.get(user, 0.0) + self.__earned.get(
                user, 0.0)
            if user in self.__parent:
                sponsor = self.__parent[user]
                budget = self.__delegation.get(
                    (sponsor, user), 0.0) + self.__earned.get(user, 0.0)
            outgoing = sum(
                self.__delegation.get((user, child), 0.0)
                for child in self.__children.get(user, []))
            return budget - outgoing

    def __total_credit_limit(self) -> float:
        return sum(self.credit_limit(u) for u in self.__earned)

    def __required_delegation(self, user: str, _depth: int = 0) -> float:
        if _depth > 50:
            raise ProtocolError(f"delegation chain too deep for {user}")
        if user in self.__seeds:
            return 0.0
        child_req = sum(
            self.__required_delegation(c, _depth + 1)
            for c in self.__children.get(user, []))
        return max(
            0.0,
            self.__principal.get(user, 0.0) + child_req -
            self.__earned.get(user, 0.0))

    def __path_to_seed(self, user: str) -> list[str]:
        self.__require_user(user)
        path: list[str] = [user]
        current: str = user
        seen: set[str] = {user}
        while current not in self.__seeds:
            current = self.__parent[current]
            if current in seen:
                raise ProtocolError(f"cycle detected for {user}")
            seen.add(current)
            path.append(current)
        path.reverse()
        return path

    def __add_seed(self, event: Event) -> None:
        p = event.payload
        user: str = get_non_empty(p, "user")
        budget: float = get_positive(p, "base_budget")
        if user in self.__earned:
            raise ProtocolError(f"user already exists: {user}")
        self.__seeds.add(user)
        self.__base_budget[user] = budget
        self.__earned[user] = 0.0
        self.__principal[user] = 0.0
        self.__children[user] = []
        self.emit(EventType.SEED_ADDED, p, correlation_id=event.correlation_id)
        self.__sync_store()

    def __add_user(self, event: Event) -> None:
        p = event.payload
        sponsor: str = get_non_empty(p, "sponsor")
        user: str = get_non_empty(p, "user")
        amount: float = get_positive(p, "delegation_amount")
        self.__require_user(sponsor)
        if user in self.__earned:
            raise ProtocolError(f"user already exists: {user}")
        if self.credit_limit(sponsor) < amount:
            raise InfeasibleOperationError("insufficient sponsor credit limit")
        self.__parent[user] = sponsor
        self.__children[user] = []
        self.__children[sponsor].append(user)
        self.__delegation[(sponsor, user)] = amount
        self.__earned[user] = 0.0
        self.__principal[user] = 0.0
        self.emit(EventType.USER_ADDED, p, correlation_id=event.correlation_id)
        self.__sync_store()

    def __repay(self, event: Event) -> None:
        p = event.payload
        user: str = get_non_empty(p, "user")
        delta: float = get_non_negative(p, "delta_earned")
        self.__require_user(user)
        self.__earned[user] += delta
        self.emit(EventType.REPAID, p, correlation_id=event.correlation_id)
        self.__sync_store()

    def __originate(self, event: Event) -> None:
        p = event.payload
        borrower: str = get_non_empty(p, "borrower")
        principal: float = get_positive(p, "principal")
        term: float = get_positive(p, "term")
        dp: float = get_finite(p, "default_probability", 0.0)
        pr: float = get_finite(p, "protocol_rate", 0.0)
        mdr: float = get_finite(p, "max_delegation_rate", 0.0)

        self.__require_user(borrower)
        if self.credit_limit(borrower) < principal:
            raise InfeasibleOperationError("principal exceeds credit limit")
        if pr < 0:
            raise ProtocolError("rates must be >= 0")
        if mdr < 0:
            raise ProtocolError("rates must be >= 0")
        if not (0.0 < dp < 1.0):
            raise ProtocolError("default probability must be in (0,1)")

        protocol_premium: float = pr * principal * term
        self.__principal[borrower] = self.__principal.get(borrower,
                                                          0.0) + principal
        loan: dict[str, Any] = {
            "borrower": borrower,
            "principal": principal,
            "term": term,
            "default_probability": dp,
            "protocol_rate": pr,
            "max_delegation_rate": mdr,
            "protocol_premium": protocol_premium,
        }
        self.__loans.setdefault(borrower, []).append(loan)
        p["protocol_premium"] = protocol_premium
        self.emit(EventType.LOAN_ORIGINATED,
                  p,
                  correlation_id=event.correlation_id)
        self.__sync_store()

    def __default(self, event: Event) -> None:
        p = event.payload
        borrower: str = get_non_empty(p, "borrower")
        self.__require_user(borrower)
        borrower_principal: float = self.__principal.get(borrower, 0.0)
        if borrower_principal <= 0:
            raise InfeasibleOperationError("no outstanding principal")

        absorb: float = min(self.__earned.get(borrower, 0.0),
                            borrower_principal)
        self.__earned[borrower] = self.__earned.get(borrower, 0.0) - absorb
        loss: float = borrower_principal - absorb

        current: str = borrower
        while loss > 0 and current not in self.__seeds:
            sponsor: str = self.__parent[current]
            edge: tuple[str, str] = (sponsor, current)
            sponsor_absorb: float = min(self.__earned.get(sponsor, 0.0), loss)
            self.__earned[sponsor] = self.__earned.get(sponsor,
                                                       0.0) - sponsor_absorb
            loss -= sponsor_absorb
            if loss > 0:
                current_edge_amount: float = self.__delegation.get(edge, 0.0)
                if current_edge_amount < loss:
                    raise ProtocolError(
                        "insufficient delegation for default propagation")
                self.__delegation[edge] = current_edge_amount - loss
            current = sponsor

        if loss > 0:
            if current not in self.__seeds:
                raise ProtocolError("residual loss did not reach seed")
            seed_budget: float = self.__base_budget.get(current, 0.0)
            if seed_budget < loss:
                raise ProtocolError("seed base budget overdraft")
            self.__base_budget[current] = seed_budget - loss

        self.__principal[borrower] = 0.0
        self.__loans.pop(borrower, None)
        self.emit(EventType.DEFAULT_OCCURRED,
                  p,
                  correlation_id=event.correlation_id)
        self.__sync_store()

    def __revoke(self, event: Event) -> None:
        p = event.payload
        sponsor: str = get_non_empty(p, "sponsor")
        child: str = get_non_empty(p, "child")
        new_amount: float = get_non_negative(p, "new_delegation")
        self.__require_user(sponsor)
        self.__require_user(child)
        edge: tuple[str, str] = (sponsor, child)
        if edge not in self.__delegation:
            raise ProtocolError("unknown delegation edge")
        if self.__parent.get(child) != sponsor:
            raise ProtocolError("not the parent-child edge")
        needed: float = self.__required_delegation(child)
        if new_amount < needed:
            raise InfeasibleOperationError(
                "revocation would make subtree insolvent")
        old_amount: float = self.__delegation[edge]
        if new_amount > old_amount:
            delta: float = new_amount - old_amount
            if self.credit_limit(sponsor) < delta:
                raise InfeasibleOperationError(
                    "insufficient credit limit to increase delegation")
        self.__delegation[edge] = new_amount
        self.emit(EventType.REVOKED, p, correlation_id=event.correlation_id)
        self.__sync_store()

    def __quote(self, event: Event) -> None:
        p = event.payload
        borrower: str = get_non_empty(p, "borrower")
        principal: float = get_finite(p, "principal", 0.0)
        term: float = get_positive(p, "term")
        dp: float = get_finite(p, "default_probability", 0.02)
        pr: float = get_finite(p, "protocol_rate", 0.0)

        if not (0.0 < dp < 1.0):
            raise ProtocolError("default probability must be in (0,1)")
        clamped_dp: float = max(min(dp, 1.0 - EPSILON), EPSILON)
        clamped_term: float = max(term, EPSILON)
        one_minus_dp: float = 1.0 - clamped_dp
        break_even: float = min(
            clamped_dp / (one_minus_dp * clamped_term), 1e6)
        protocol_premium: float = pr * principal * term
        self.emit(EventType.QUOTE_CALCULATED, {
            "borrower": borrower,
            "principal": principal,
            "term": term,
            "default_probability": dp,
            "protocol_rate": pr,
            "protocol_premium": protocol_premium,
            "break_even_rate": break_even,
        },
                  correlation_id=event.correlation_id)

    # -- state persistence ---------------------------------------------------

    def __load_store(self) -> None:
        with self.__lock:
            raw = self.store.get("protocol:state")
            if raw is None:
                return
            self.__seeds = set(raw.get("seeds", []))
            self.__parent = dict(raw.get("parent", {}))
            self.__children = {
                k: list(v) for k, v in raw.get("children", {}).items()
            }
            delegation_raw = raw.get("delegation", {})
            self.__delegation = {}
            for k, v in delegation_raw.items():
                s, c = k.split("->", 1)
                self.__delegation[(s, c)] = v
            self.__base_budget = dict(raw.get("base_budget", {}))
            self.__earned = dict(raw.get("earned", {}))
            self.__principal = dict(raw.get("principal", {}))
            loans_raw = raw.get("loans", [])
            self.__loans = {}
            for loan in loans_raw:
                b = loan.get("borrower", "")
                self.__loans.setdefault(b, []).append(loan)

    def __sync_store(self) -> None:
        with self.__lock:
            state: dict[str, Any] = {
                "seeds":
                    sorted(self.__seeds),
                "parent":
                    dict(self.__parent),
                "children": {
                    k: list(v) for k, v in self.__children.items()
                },
                "delegation": {
                    f"{s}->{c}": v for (s, c), v in self.__delegation.items()
                },
                "base_budget":
                    dict(self.__base_budget),
                "earned":
                    dict(self.__earned),
                "principal":
                    dict(self.__principal),
                "loans": [
                    loan for borrower_loans in self.__loans.values()
                    for loan in borrower_loans
                ],
            }
            self.store.set("protocol:state", state)
