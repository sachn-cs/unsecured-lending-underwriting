"""Command-line demo for delegated underwriting baseline workflow."""

from __future__ import annotations

import argparse
import json
from typing import Any

from loguru import logger

from ulu.core.mechanism import DelegatedUnderwriting


def quote_report(quote: Any) -> dict[str, Any]:
    """Builds printable quote summary payload."""
    return {
        "protocol_premium": quote.protocol_premium,
        "delegation_premium": quote.delegation_premium,
        "total_interest": quote.total_interest,
        "locked_by_edge": {
            f"{source}->{target}": amount
            for (source, target), amount in quote.locked_by_edge.items()
        },
        "payouts": quote.delegation_payouts,
    }


def theorem_checks(mechanism: DelegatedUnderwriting, before_total: float, principal: float) -> dict[str, Any]:
    """Evaluates post-operation theorem checks."""
    checks = {}
    # Theorem 1: credit conservation
    lhs = mechanism.total_credit_limit()
    rhs = sum(mechanism.base_budget[s] for s in mechanism.seeds) + sum(mechanism.earned.values())
    checks["theorem_1_credit_conservation"] = {
        "total_credit_limit": lhs,
        "seed_budgets_plus_earned": rhs,
        "holds": bool(abs(lhs - rhs) < 1e-9),
    }
    # Theorem 4: aggregate credit fell by principal
    checks["theorem_4_aggregate_drop"] = {
        "expected_drop": principal,
        "actual_drop": before_total - lhs,
        "holds": bool(abs((before_total - lhs) - principal) < 1e-9),
    }
    return checks


def run_demo(state_path: str | None = None) -> None:
    """Runs full demo flow: setup, quote, originate, repay, default, revoke."""
    logger.info("starting demo")

    mechanism = DelegatedUnderwriting()
    mechanism.add_seed("seed", 100.0)
    mechanism.add_user("seed", "alice", 40.0)
    mechanism.add_user("alice", "bob", 22.0)

    quote = mechanism.quote_loan(
        borrower="bob",
        principal=10.0,
        term=1.0,
        default_probability=0.15,
        protocol_rate=0.2,
        max_delegation_rate=0.1,
    )
    mechanism.originate_loan(
        borrower="bob",
        principal=10.0,
        term=1.0,
        default_probability=0.15,
        protocol_rate=0.2,
        max_delegation_rate=0.1,
    )

    mechanism.repay("bob", 2.5)

    before_total = mechanism.total_credit_limit()
    mechanism.default("bob")
    checks_after_default = theorem_checks(mechanism, before_total, principal=10.0)

    required = mechanism.required_delegation("bob")
    mechanism.revoke("alice", "bob", required)

    if state_path:
        mechanism.save_json(state_path)
        mechanism = DelegatedUnderwriting.load_json(state_path)

    mechanism.assert_invariants()

    report = {
        "quote": quote_report(quote),
        "theorem_checks": checks_after_default,
        "final_state": {
            "base_budget": mechanism.base_budget,
            "earned": mechanism.earned,
            "principal": mechanism.principal,
            "delegations": {
                f"{source}->{target}": amount
                for (source, target), amount in mechanism.delegation.items()
            },
            "credit_limits": {
                user: mechanism.credit_limit(user)
                for user in sorted(mechanism.earned)
            },
            "total_credit_limit": mechanism.total_credit_limit(),
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))


def main() -> None:
    """Parses command-line arguments and executes selected demo command."""
    parser = argparse.ArgumentParser(description="Delegated underwriting demo")
    parser.add_argument("command", choices=["run-demo"], help="run demo workflow")
    parser.add_argument(
        "--state-path",
        default=None,
        help="optional JSON path for persistence round-trip",
    )
    args = parser.parse_args()
    if args.command == "run-demo":
        run_demo(state_path=args.state_path)


if __name__ == "__main__":
    main()
