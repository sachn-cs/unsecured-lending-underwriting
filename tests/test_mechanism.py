"""Exhaustive tests for MechanismService — the core state machine.

Covers every state transition, every edge case, and all invariants.
"""

from __future__ import annotations

from typing import Any

import pytest

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.__exceptions__ import ProtocolError
from underwrite.__store__ import MemoryStore
from underwrite.services.mechanism.service import MechanismService


def make_svc() -> MechanismService:
    return MechanismService(service_id="test-mech",
                            bus=LocalBus(),
                            store=MemoryStore())


def command(svc: MechanismService,
            cmd: str,
            payload: dict[str, Any],
            corr: str = "") -> None:
    svc.handle(
        Event(
            event_type="mechanism",
            source="test",
            payload={
                "command": cmd,
                **payload
            },
            correlation_id=corr,
        ))


class TestAddSeed:

    def test_adds_seed(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        assert "bank" in svc.earned

    def test_rejects_duplicate_user(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_seed", {"user": "bank", "base_budget": 50_000})
        assert svc.earned["bank"] == 0.0

    def test_rejects_zero_budget(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 0})
        assert "bank" not in svc.earned

    def test_rejects_negative_budget(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": -100})
        assert "bank" not in svc.earned

    def test_syncs_to_store(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        state = svc.store.get("protocol:state")
        assert state is not None
        assert "bank" in state["seeds"]

    def test_emits_seed_added_event(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.SEED_ADDED, lambda e: received.append(e))
        svc = MechanismService(service_id="mech", bus=bus, store=MemoryStore())
        svc.start()
        bus.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        assert len(received) == 1
        assert received[0].payload["user"] == "bank"

    def test_multiple_seeds(self) -> None:
        svc = make_svc()
        svc.start()
        for i in range(10):
            command(svc, "add_seed", {
                "user": f"bank{i}",
                "base_budget": 100_000
            })
        assert len(svc.seeds) == 10


class TestAddUser:

    def test_adds_user_under_seed(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        assert "alice" in svc.earned

    def test_rejects_unknown_sponsor(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_user", {
            "sponsor": "ghost",
            "user": "alice",
            "delegation_amount": 50_000
        })
        assert "alice" not in svc.earned

    def test_rejects_duplicate_user(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        users = list(svc.earned.keys())
        assert users.count("alice") == 1

    def test_rejects_zero_delegation(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 0
        })
        assert "alice" not in svc.earned

    def test_rejects_negative_delegation(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": -10
        })
        assert "alice" not in svc.earned

    def test_rejects_excessive_delegation(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 200_000
        })
        assert "alice" not in svc.earned

    def test_nested_delegation(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 1_000_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "a",
            "delegation_amount": 500_000
        })
        command(svc, "add_user", {
            "sponsor": "a",
            "user": "b",
            "delegation_amount": 200_000
        })
        command(svc, "add_user", {
            "sponsor": "b",
            "user": "c",
            "delegation_amount": 100_000
        })
        assert "c" in svc.earned
        assert len(svc.earned) == 4


class TestRepay:

    def test_increases_earned(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "repay", {"user": "bank", "delta_earned": 5_000})
        assert svc.earned["bank"] == 5_000

    def test_rejects_negative_delta(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "repay", {"user": "bank", "delta_earned": -100})
        assert svc.earned["bank"] == 0.0

    def test_rejects_unknown_user(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "repay", {"user": "nobody", "delta_earned": 100})
        assert "nobody" not in svc.earned

    def test_accumulates_repayments(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        for _ in range(10):
            command(svc, "repay", {"user": "bank", "delta_earned": 100})
        assert svc.earned["bank"] == 1_000


class TestOriginate:

    def test_originates_loan(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        command(
            svc, "originate", {
                "borrower": "alice",
                "principal": 10_000,
                "term": 12,
                "default_probability": 0.02,
                "protocol_rate": 0.10,
                "max_delegation_rate": 0.05,
            })
        assert svc.principal["alice"] == 10_000

    def test_rejects_exceeding_credit_limit(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        command(
            svc, "originate", {
                "borrower": "alice",
                "principal": 200_000,
                "term": 12,
                "default_probability": 0.02,
                "protocol_rate": 0.10,
                "max_delegation_rate": 0.05,
            })
        assert svc.principal.get("alice", 0) == 0

    def test_rejects_zero_principal(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        command(
            svc, "originate", {
                "borrower": "alice",
                "principal": 0,
                "term": 12,
                "default_probability": 0.02,
                "protocol_rate": 0.10,
                "max_delegation_rate": 0.05,
            })
        assert svc.principal.get("alice", 0) == 0

    def test_rejects_negative_term(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        command(
            svc, "originate", {
                "borrower": "alice",
                "principal": 10_000,
                "term": -1,
                "default_probability": 0.02,
                "protocol_rate": 0.10,
                "max_delegation_rate": 0.05,
            })
        assert svc.principal.get("alice", 0) == 0

    def test_rejects_invalid_default_probability(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        command(
            svc, "originate", {
                "borrower": "alice",
                "principal": 10_000,
                "term": 12,
                "default_probability": 1.5,
                "protocol_rate": 0.10,
                "max_delegation_rate": 0.05,
            })
        assert svc.principal.get("alice", 0) == 0

    def test_multiple_loans_same_borrower(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 1_000_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 500_000
        })
        for _ in range(5):
            command(
                svc, "originate", {
                    "borrower": "alice",
                    "principal": 50_000,
                    "term": 12,
                    "default_probability": 0.02,
                    "protocol_rate": 0.10,
                    "max_delegation_rate": 0.05,
                })
        assert svc.principal["alice"] == 250_000


class TestDefault:

    def test_absorbs_from_earned(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        command(
            svc, "originate", {
                "borrower": "alice",
                "principal": 10_000,
                "term": 12,
                "default_probability": 0.02,
                "protocol_rate": 0.10,
                "max_delegation_rate": 0.05,
            })
        command(svc, "repay", {"user": "alice", "delta_earned": 3_000})
        command(svc, "default", {"borrower": "alice"})
        assert svc.principal["alice"] == 0.0
        assert svc.earned["alice"] == 0.0

    def test_propagates_loss_to_sponsor(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        command(
            svc, "originate", {
                "borrower": "alice",
                "principal": 10_000,
                "term": 12,
                "default_probability": 0.02,
                "protocol_rate": 0.10,
                "max_delegation_rate": 0.05,
            })
        command(svc, "default", {"borrower": "alice"})
        assert svc.principal["alice"] == 0.0

    def test_rejects_default_with_no_principal(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        command(svc, "default", {"borrower": "alice"})
        assert svc.principal.get("alice", 0) == 0

    def test_multi_level_propagation(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 1_000_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "a",
            "delegation_amount": 500_000
        })
        command(svc, "add_user", {
            "sponsor": "a",
            "user": "b",
            "delegation_amount": 200_000
        })
        command(svc, "add_user", {
            "sponsor": "b",
            "user": "c",
            "delegation_amount": 100_000
        })
        command(
            svc, "originate", {
                "borrower": "c",
                "principal": 50_000,
                "term": 12,
                "default_probability": 0.02,
                "protocol_rate": 0.10,
                "max_delegation_rate": 0.05,
            })
        command(svc, "default", {"borrower": "c"})
        assert svc.principal["c"] == 0.0


class TestRevoke:

    def test_reduces_delegation(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        command(svc, "revoke", {
            "sponsor": "bank",
            "child": "alice",
            "new_delegation": 10_000
        })
        state = svc.store.get("protocol:state")
        assert state is not None
        assert state["delegation"]["bank->alice"] == 10_000

    def test_rejects_negative_new_delegation(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        command(svc, "revoke", {
            "sponsor": "bank",
            "child": "alice",
            "new_delegation": -10
        })
        state = svc.store.get("protocol:state")
        assert state["delegation"]["bank->alice"] == 50_000

    def test_rejects_unknown_edge(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "revoke", {
            "sponsor": "bank",
            "child": "alice",
            "new_delegation": 10
        })
        state = svc.store.get("protocol:state")
        assert state is None or "bank->alice" not in state.get("delegation", {})


class TestCreditLimit:

    def test_seed_credit_limit(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        cl: float = svc.credit_limit("bank")
        assert cl == 100_000.0

    def test_user_credit_limit_equals_delegation(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        cl: float = svc.credit_limit("alice")
        assert cl == 50_000.0

    def test_user_credit_limit_with_earned(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        command(svc, "repay", {"user": "alice", "delta_earned": 5_000})
        cl: float = svc.credit_limit("alice")
        assert cl == 55_000.0


class TestQuote:

    def test_quote_calculated(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.QUOTE_CALCULATED, lambda e: received.append(e))
        svc = MechanismService(service_id="mech", bus=bus, store=MemoryStore())
        svc.start()
        bus.start()
        command(
            svc, "quote", {
                "borrower": "alice",
                "principal": 10_000,
                "term": 12,
                "default_probability": 0.02,
                "protocol_rate": 0.10,
            })
        assert len(received) == 1
        assert received[0].payload["protocol_premium"] == 12_000.0


class TestStateSync:

    def test_state_persisted_after_each_mutation(self) -> None:
        svc = make_svc()
        svc.start()
        assert svc.store.get("protocol:state") is None
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        assert svc.store.get("protocol:state") is not None

    def test_state_contains_full_snapshot(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        state = svc.store.get("protocol:state")
        assert "bank" in state["seeds"]
        assert state["parent"]["alice"] == "bank"


class TestEdgeCases:

    def test_empty_state(self) -> None:
        svc = make_svc()
        assert len(svc.earned) == 0
        assert len(svc.seeds) == 0

    def test_self_sponsorship_rejected(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "bank",
            "delegation_amount": 10
        })
        assert svc.earned.get("bank", 0) == 0.0

    def test_repay_then_originate_then_default_cycle(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 1_000_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "a",
            "delegation_amount": 500_000
        })
        command(svc, "add_user", {
            "sponsor": "a",
            "user": "b",
            "delegation_amount": 200_000
        })
        command(
            svc, "originate", {
                "borrower": "b",
                "principal": 50_000,
                "term": 12,
                "default_probability": 0.02,
                "protocol_rate": 0.10,
                "max_delegation_rate": 0.05,
            })
        command(svc, "repay", {"user": "b", "delta_earned": 10_000})
        command(svc, "default", {"borrower": "b"})
        assert svc.principal["b"] == 0.0

    def test_revoke_to_zero(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "a",
            "delegation_amount": 50_000
        })
        command(svc, "revoke", {
            "sponsor": "bank",
            "child": "a",
            "new_delegation": 0
        })
        state = svc.store.get("protocol:state")
        assert state["delegation"]["bank->a"] == 0

    def test_originate_uses_all_credit(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc, "add_user", {
            "sponsor": "bank",
            "user": "a",
            "delegation_amount": 50_000
        })
        command(
            svc, "originate", {
                "borrower": "a",
                "principal": 50_000,
                "term": 12,
                "default_probability": 0.02,
                "protocol_rate": 0.10,
                "max_delegation_rate": 0.05,
            })
        assert svc.principal["a"] == 50_000

    def test_unknown_command_silently_ignored(self) -> None:
        svc = make_svc()
        svc.start()
        command(svc, "nonexistent_cmd", {})
        assert len(svc.earned) == 0

    def test_deep_delegation_chain_raises(self) -> None:
        svc = make_svc()
        svc.start()
        # Build chain root → u0 → u1 → ... → u54 (55 non-seed users).
        # Each user delegates 1 less than they receive so credit_limit passes.
        command(svc, "add_seed", {"user": "root", "base_budget": 10_000_000})
        prev = "root"
        for i in range(55):
            user = f"u{i}"
            amt = 200_000 - i
            command(svc, "add_user", {
                "sponsor": prev,
                "user": user,
                "delegation_amount": amt,
            })
            prev = user
        # __required_delegation("u0") traverses 0→1→…→54, hitting depth 54 > 50.
        # Access via an internal call since handle propagates ProtocolError to the bus DLQ.
        with pytest.raises(ProtocolError, match="delegation chain too deep"):
            with svc._MechanismService__state_lock:
                svc._MechanismService__required_delegation("u0")


class TestMechanismStoreLoad:

    def test_loads_state_from_store_on_init(self) -> None:
        store = MemoryStore()
        svc1 = MechanismService(service_id="mech", bus=LocalBus(), store=store)
        svc1.start()
        command(svc1, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(svc1, "add_user", {
            "sponsor": "bank",
            "user": "alice",
            "delegation_amount": 50_000
        })
        # Fresh service from same store should restore state
        svc2 = MechanismService(service_id="mech", bus=LocalBus(), store=store)
        svc2.start()
        assert "bank" in svc2.earned
        assert "alice" in svc2.earned
        assert svc2.credit_limit("alice") == 50_000

    def test_empty_store_initializes_empty_state(self) -> None:
        store = MemoryStore()
        svc = MechanismService(service_id="mech", bus=LocalBus(), store=store)
        svc.start()
        assert len(svc.earned) == 0
        assert svc.credit_limit("alice") == 0.0

    def test_partial_state_restores_gracefully(self) -> None:
        store = MemoryStore()
        store.set("protocol:state", {
            "seeds": ["bank"],
            "earned": {
                "bank": 0.0
            }
        })
        svc = MechanismService(service_id="mech", bus=LocalBus(), store=store)
        svc.start()
        assert "bank" in svc.earned
        # Test through public API: bank is seed with no base_budget, credit_limit uses 0
        assert svc.credit_limit("bank") == 0.0


class TestMechanismStateOrdering:

    def test_add_seed_emits_after_persist(self) -> None:
        captured: dict[str, Any] = {}

        def spy(event_type: str,
                payload: dict[str, Any],
                correlation_id: str = "") -> None:
            if event_type == EventType.SEED_ADDED:
                captured["emit_seen"] = True
                captured["user_in_earned_at_emit"] = payload[
                    "user"] in svc.earned

        svc = make_svc()
        svc.emit = spy  # type: ignore[assignment]
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        assert captured.get("emit_seen") is True
        # Emit fires after state is persisted, so the user is already in earned
        assert captured.get("user_in_earned_at_emit") is True

    def test_originate_emits_after_persist(self) -> None:
        captured: dict[str, Any] = {}

        def spy(event_type: str,
                payload: dict[str, Any],
                correlation_id: str = "") -> None:
            if event_type == EventType.LOAN_ORIGINATED:
                captured["emit_seen"] = True
                captured["loans_at_emit"] = len(
                    svc._MechanismService__loans.get("bank", []))

        svc = make_svc()
        svc.emit = spy  # type: ignore[assignment]
        svc.start()
        command(svc, "add_seed", {"user": "bank", "base_budget": 100_000})
        command(
            svc, "originate", {
                "borrower": "bank",
                "principal": 10000,
                "term": 12,
                "default_probability": 0.02,
                "protocol_rate": 0.1,
                "max_delegation_rate": 0.5,
            })
        assert captured.get("emit_seen") is True
        # Emit fires after state is persisted, so the loan IS in the loans list
        assert captured.get("loans_at_emit") == 1
