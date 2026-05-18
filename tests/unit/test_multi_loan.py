"""Unit tests for multi-loan per borrower support."""

from __future__ import annotations

from ulu.core.mechanism import DelegatedUnderwriting


class TestMultiLoan:
    def test_originate_two_loans(self) -> None:
        engine = DelegatedUnderwriting()
        engine.add_seed("s", 1000.0)
        engine.add_user("s", "b", 500.0)
        q1 = engine.originate_loan("b", 50.0, 1.0, 0.1, 0.2, 0.05)
        q2 = engine.originate_loan("b", 30.0, 1.0, 0.1, 0.2, 0.05)
        assert engine.principal["b"] == 80.0
        assert len(engine.list_loans("b")) == 2
        assert q1.principal == 50.0
        assert q2.principal == 30.0

    def test_default_clears_all_loans(self) -> None:
        engine = DelegatedUnderwriting()
        engine.add_seed("s", 1000.0)
        engine.add_user("s", "b", 500.0)
        engine.originate_loan("b", 50.0, 1.0, 0.1, 0.2, 0.05)
        engine.originate_loan("b", 30.0, 1.0, 0.1, 0.2, 0.05)
        engine.default("b")
        assert engine.principal["b"] == 0.0
        assert engine.list_loans("b") == []

    def test_repay_does_not_affect_loan_list(self) -> None:
        engine = DelegatedUnderwriting()
        engine.add_seed("s", 1000.0)
        engine.add_user("s", "b", 500.0)
        engine.originate_loan("b", 50.0, 1.0, 0.1, 0.2, 0.05)
        engine.repay("b", 10.0)
        assert len(engine.list_loans("b")) == 1
        assert engine.principal["b"] == 50.0
