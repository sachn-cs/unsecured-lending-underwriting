"""Load/stress testing suite using Locust.

Item 70 from production roadmap.
"""

from __future__ import annotations

from locust import HttpUser, between, task


class UluApiUser(HttpUser):
    """Simulates API consumer interacting with ULU endpoints."""

    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        self.client.get("/health")
        self.client.get("/ready")

    @task(3)
    def get_health(self) -> None:
        self.client.get("/health")

    @task(2)
    def get_ready(self) -> None:
        self.client.get("/ready")

    @task(1)
    def get_metrics(self) -> None:
        self.client.get("/metrics")

    @task(1)
    def get_openapi(self) -> None:
        self.client.get("/openapi.json")

    @task(2)
    def seed_and_quote_flow(self) -> None:
        sponsor = f"sponsor_{self.user_id}"
        borrower = f"borrower_{self.user_id}"
        self.client.post("/seed", json={"user": sponsor, "base_budget": 10000.0})
        self.client.post("/user", json={"sponsor": sponsor, "user": borrower, "delegation_amount": 5000.0})
        self.client.post(
            "/quote",
            json={
                "borrower": borrower,
                "principal": 1000.0,
                "term": 1.0,
                "default_probability": 0.2,
                "protocol_rate": 0.3,
                "max_delegation_rate": 0.1,
            },
        )

    @task(1)
    def loan_lifecycle(self) -> None:
        sponsor = f"sponsor_lc_{self.user_id}"
        borrower = f"borrower_lc_{self.user_id}"
        self.client.post("/seed", json={"user": sponsor, "base_budget": 10000.0})
        self.client.post("/user", json={"sponsor": sponsor, "user": borrower, "delegation_amount": 5000.0})
        self.client.post(
            "/originate",
            json={
                "borrower": borrower,
                "principal": 500.0,
                "term": 1.0,
                "default_probability": 0.1,
                "protocol_rate": 0.2,
                "max_delegation_rate": 0.05,
            },
        )
        self.client.post("/repay", json={"user": borrower, "delta_earned": 10.0})

    @task(1)
    def get_graph(self) -> None:
        self.client.get("/admin/graph")

    @task(1)
    def get_utilization(self) -> None:
        self.client.get("/admin/utilization")
