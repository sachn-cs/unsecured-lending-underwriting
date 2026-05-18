"""API version prefix middleware for backward-compatible endpoint evolution.

Item 62 from production roadmap.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ulu.infra.logging import logger


class VersioningMiddleware(BaseHTTPMiddleware):
    """Injects API version from request path into state for downstream use.

    Routes like /v1/seed and /v2/seed are supported. The version is stripped
    before routing so that FastAPI routers do not need duplicate definitions.
    """

    SUPPORTED_VERSIONS = {"v1", "v2"}
    DEFAULT_VERSION = "v1"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        version = self.DEFAULT_VERSION
        for v in self.SUPPORTED_VERSIONS:
            prefix = f"/{v}/"
            if path.startswith(prefix):
                version = v
                request.scope["path"] = path[len(prefix) - 1 :]  # restore leading /
                break
        request.state.api_version = version
        logger.debug("api_version_detected", version=version, original_path=path)
        response = await call_next(request)
        response.headers["X-API-Version"] = version
        return response
