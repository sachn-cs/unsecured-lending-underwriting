"""FastAPI application exposing delegated-underwriting operations."""

from __future__ import annotations

from time import perf_counter

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from ulu.api.middleware import CorrelationIdMiddleware, TimingMiddleware
from ulu.api.routers import admin, health, ledger, loans, repayments, revocations, seeds, state, users
from ulu.api.schemas import ErrorResponse
from ulu.api.service import limiter, service  # noqa: F401
from ulu.infra.logging import logger

REQUESTS_TOTAL = Counter(
    "ulu_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
REQUEST_ERRORS_TOTAL = Counter(
    "ulu_request_errors_total",
    "Total HTTP request errors",
    ["method", "endpoint"],
)
REQUEST_LATENCY = Histogram(
    "ulu_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
)
IDEMPOTENCY_HITS_TOTAL = Counter(
    "ulu_idempotency_hits_total",
    "Total idempotency cache hits",
)
IDEMPOTENCY_CONFLICTS_TOTAL = Counter(
    "ulu_idempotency_conflicts_total",
    "Total idempotency key conflicts",
)

app = FastAPI(title="ULU API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(detail=exc.detail).model_dump(),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled_exception")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(detail="internal server error").model_dump(),
    )


app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(TimingMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_middleware(request, call_next):
    """Collects lightweight request metrics."""
    start = perf_counter()
    response = await call_next(request)
    elapsed = perf_counter() - start
    route = request.scope.get("route")
    endpoint = route.name if route else "unknown"
    REQUESTS_TOTAL.labels(method=request.method, endpoint=endpoint, status=str(response.status_code)).inc()
    REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).observe(elapsed)
    if response.status_code >= 400:
        REQUEST_ERRORS_TOTAL.labels(method=request.method, endpoint=endpoint).inc()
    return response


app.include_router(health.router)
app.include_router(seeds.router)
app.include_router(users.router)
app.include_router(loans.router)
app.include_router(repayments.router)
app.include_router(revocations.router)
app.include_router(state.router)
app.include_router(ledger.router)
app.include_router(admin.router)
