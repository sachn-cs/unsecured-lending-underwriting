"""SQLAlchemy async query tracing hooks for distributed tracing.

Item 60 from production roadmap.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine

from ulu.infra.logging import logger
from ulu.infra.tracing import Tracer


class DbTracingHooks:
    """Attaches SQLAlchemy event listeners that emit trace spans per query."""

    def __init__(self, tracer: Tracer | None = None) -> None:
        self.tracer = tracer

    def _log_query(self, statement: str, parameters: Any, duration_ms: float) -> None:
        logger.debug(
            "sql_query_executed",
            statement=statement[:200],
            duration_ms=duration_ms,
            param_count=len(parameters) if isinstance(parameters, (list, tuple)) else 1,
        )

    def _before_cursor(
        self,
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        context._ulu_query_start = time.time()  # type: ignore[attr-defined]

    def _after_cursor(
        self,
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        start = getattr(context, "_ulu_query_start", None)
        duration_ms = (time.time() - start) * 1000.0 if start else 0.0
        self._log_query(statement, parameters, duration_ms)
        if self.tracer is not None:
            with self.tracer.span("sqlalchemy.query", attributes={"statement": statement[:200]}):
                pass

    def attach(self, engine: Engine) -> None:
        event.listen(engine, "before_cursor_execute", self._before_cursor)
        event.listen(engine, "after_cursor_execute", self._after_cursor)
        logger.info("db_tracing_hooks_attached")

    def detach(self, engine: Engine) -> None:
        event.remove(engine, "before_cursor_execute", self._before_cursor)
        event.remove(engine, "after_cursor_execute", self._after_cursor)
        logger.info("db_tracing_hooks_detached")
