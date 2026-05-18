"""Unit tests for SQLAlchemy DB tracing hooks."""

from __future__ import annotations

from sqlalchemy import create_engine, text

from ulu.infra.db_tracing import DbTracingHooks
from ulu.infra.tracing import Tracer


class TestDbTracingHooks:
    def test_attach_emits_span(self) -> None:
        tracer = Tracer("test")
        hooks = DbTracingHooks(tracer=tracer)
        engine = create_engine("sqlite:///:memory:")
        hooks.attach(engine)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        hooks.detach(engine)
        sql_spans = [s for s in tracer.spans if s.name == "sqlalchemy.query"]
        assert len(sql_spans) >= 1
        assert "SELECT 1" in sql_spans[0].attributes.get("statement", "")

    def test_detach_stops_emitting(self) -> None:
        tracer = Tracer("test")
        hooks = DbTracingHooks(tracer=tracer)
        engine = create_engine("sqlite:///:memory:")
        hooks.attach(engine)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        hooks.detach(engine)
        before = len(tracer.spans)
        with engine.connect() as conn:
            conn.execute(text("SELECT 2"))
        after = len(tracer.spans)
        assert after == before

    def test_noop_tracer_does_not_crash(self) -> None:
        from ulu.infra.tracing import NoOpTracer

        hooks = DbTracingHooks(tracer=NoOpTracer())
        engine = create_engine("sqlite:///:memory:")
        hooks.attach(engine)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        hooks.detach(engine)
