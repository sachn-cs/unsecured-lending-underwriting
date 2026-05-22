"""CLI for the underwrite nano-service platform.

Usage:
    underwrite init [PATH]              Create default config file
    underwrite run <service>...         Start one or more services
    underwrite list                     List all available services
    underwrite identity <service>       Generate identity for a service
    underwrite health                   Show system health status
    underwrite dlq                      Show dead-letter queue info
    underwrite metrics                  Show metrics snapshot
    underwrite migrate                  Run pending schema migrations
"""

from __future__ import annotations

import signal
import time
from pathlib import Path
from typing import Any

import typer

from underwrite.__config__ import SERVICE_NAMES, Configuration, ServiceConfig
from underwrite.__identity__ import Identity
from underwrite.__runtime__ import Runtime

app = typer.Typer(
    name="underwrite",
    help="Delegated Underwriting Protocol — nano-service platform",
    no_args_is_help=True,
)


def _load_config() -> Configuration:
    """Loads configuration from disk or returns defaults.

    Returns:
        A Configuration instance, either from ``underwrite.json``
        or a default config if the file does not exist.
    """
    config_path: str = "underwrite.json"
    if Path(config_path).exists():
        return Configuration.load(config_path)
    return Configuration.default()


@app.command()
def init(
    path: str = typer.Argument(
        "underwrite.json",
        help="Path to write the configuration file",
    ),
) -> None:
    """Creates a default configuration file."""
    if Path(path).exists():
        typer.secho(f"Configuration already exists: {path}",
                    err=True,
                    fg=typer.colors.RED)
        raise typer.Exit(code=1)
    config = Configuration.default()
    config.services["mechanism"] = ServiceConfig(enabled=True)
    config.services["audit"] = ServiceConfig(enabled=True)
    config.save(path)
    typer.echo(f"Configuration written to {path}")


_SERVICE_ARG = typer.Argument(
    ...,
    help="One or more nano services to start",
    metavar="SERVICE",
)


@app.command()
def run(
    services: list[str] = _SERVICE_ARG,
) -> None:
    """Starts one or more nano services."""
    for name in services:
        if name not in SERVICE_NAMES:
            typer.secho(f"Unknown service: {name}",
                        err=True,
                        fg=typer.colors.RED)
            typer.echo(f"Available: {', '.join(SERVICE_NAMES)}")
            raise typer.Exit(code=1)

    config = _load_config()
    runtime = Runtime(config)

    def handle_signal(signum: int, frame: object) -> None:
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, handle_signal)

    try:
        runtime.start(services)
        typer.echo(f"Running: {', '.join(services)}")
        typer.echo("Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        typer.echo("\nShutting down...")
    finally:
        runtime.stop()
        typer.echo("Stopped.")


@app.command()
def list_services() -> None:
    """Lists all available nano services."""
    typer.echo("Available nano services:")
    for name in SERVICE_NAMES:
        typer.echo(f"  - {name}")


@app.command()
def identity(
    service_name: str = typer.Argument(
        ...,
        help="Service name to generate identity for",
    ),
) -> None:
    """Generates an Ed25519 identity for a service."""
    try:
        from underwrite.__identity__ import HAS_CRYPTO
    except ImportError:
        HAS_CRYPTO = False
    if not HAS_CRYPTO:
        typer.secho(
            "Warning: cryptography library not available — "
            "identity will use dummy (insecure) keys",
            err=True,
            fg=typer.colors.YELLOW,
        )
    try:
        ident: Identity = Identity.create(service_name)
    except Exception as exc:
        typer.secho(f"Failed to create identity: {exc}",
                    err=True,
                    fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    typer.echo(f"Identity for: {service_name}")
    typer.echo(f"  Public key:  {ident.public_key}")
    typer.echo("  Private key: (stored only in memory / TPM — not printable)")


@app.command()
def health() -> None:
    """Shows system health status."""
    config = _load_config()
    runtime = Runtime(config)
    status = runtime.health.status()
    typer.echo(f"Status: {status['status']}")
    typer.echo(f"OK: {status['ok']}")
    typer.echo("Checks:")
    for name, result in status["checks"].items():
        ok = result.get("ok", False)
        detail = result.get("detail", "")
        icon = "OK" if ok else "FAIL"
        line = f"  [{icon}] {name}"
        if detail:
            line += f" — {detail}"
        typer.echo(line)
    if not status["ok"]:
        raise typer.Exit(code=1)


@app.command()
def dlq() -> None:
    """Shows dead-letter queue info."""
    config = _load_config()
    runtime = Runtime(config)
    records = runtime.bus.dlq
    typer.echo(f"Dead-letter queue: {records.count} entries")
    for r in records.records[:20]:
        typer.echo(
            f"  [{r.timestamp:.1f}] {r.subscriber_id}: "
            f"{r.event.event_type} — {r.error[:60]}",)
    if records.count > 20:
        typer.echo(f"  ... and {records.count - 20} more")


@app.command()
def metrics() -> None:
    """Shows a metrics snapshot."""
    config = _load_config()
    runtime = Runtime(config)
    mc = runtime.metrics
    if not mc:
        typer.echo("Metrics disabled")
        return
    snap = mc.snapshot()
    typer.echo("Counters:")
    for k, c in snap.get("counters", {}).items():
        typer.echo(f"  {k}: {c['value']}")
    typer.echo("Timers:")
    for k, t in snap.get("timers", {}).items():
        typer.echo(
            f"  {k}: count={t['count']} avg={t['avg_ms']:.1f}ms "
            f"min={t['min_ms']:.1f}ms max={t['max_ms']:.1f}ms",)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind address"),
    port: int = typer.Option(8080, help="Bind port"),
    services: str = typer.Option(
        "mechanism,audit", help="Comma-separated list of services to start"),
    rate_limit: int = typer.Option(
        100, help="Max requests per second for health/metrics endpoints"),
) -> None:
    """Starts the Runtime as an HTTP daemon with health/metrics endpoints."""
    try:
        import uvicorn
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
    except ImportError:
        typer.secho(
            "serve requires uvicorn and fastapi; install with: pip install underwrite[serve]",
            err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from None

    import time as _time

    config = _load_config()
    rt = Runtime(config)
    app_fastapi = FastAPI(title="underwrite", version="0.1.0")

    # Token-bucket rate limiter
    _bucket_tokens: float = float(rate_limit)
    _bucket_last: float = _time.monotonic()

    @app_fastapi.middleware("http")
    async def _rate_limit_middleware(request: Request,
                                     call_next: Any) -> JSONResponse:
        nonlocal _bucket_tokens, _bucket_last  # noqa: F824
        now = _time.monotonic()
        elapsed = now - _bucket_last
        _bucket_last = now
        _bucket_tokens = min(float(rate_limit),
                             _bucket_tokens + elapsed * rate_limit)
        if _bucket_tokens < 1.0:
            return JSONResponse(status_code=429,
                                content={"error": "rate limit exceeded"})
        _bucket_tokens -= 1.0
        return await call_next(request)

    @app_fastapi.on_event("startup")
    async def startup() -> None:
        svc_list = [s.strip() for s in services.split(",") if s.strip()]
        rt.start(svc_list)

    @app_fastapi.on_event("shutdown")
    async def shutdown() -> None:
        rt.stop()

    @app_fastapi.get("/health")
    async def health_endpoint() -> dict:
        return rt.health.status()

    @app_fastapi.get("/metrics")
    async def metrics_endpoint() -> dict:
        mc = rt.metrics
        return mc.snapshot() if mc else {"disabled": True}

    typer.echo(f"Serving on http://{host}:{port}")
    uvicorn.run(app_fastapi, host=host, port=port, log_level="info")


@app.command()
def migrate() -> None:
    """Runs pending schema migrations."""
    _load_config()
    Runtime()  # triggers auto-migrate on construction
    typer.echo("Migrations applied")


def main() -> None:
    """Entry point: delegates to the Typer app."""
    app()


if __name__ == "__main__":
    main()
