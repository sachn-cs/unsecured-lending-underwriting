"""Snapshot compression utilities for ProtocolSnapshot state payloads.

Item 127 from production roadmap.
"""

from __future__ import annotations

import gzip
from typing import Any

import orjson

from ulu.infra.logging import logger


class SnapshotCompressor:
    """Compresses and decompresses large JSON snapshot payloads using gzip."""

    @staticmethod
    def compress(payload: dict[str, Any]) -> bytes:
        """Serializes payload to JSON and compresses with gzip."""
        data = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
        compressed = gzip.compress(data, compresslevel=6)
        ratio = len(compressed) / max(len(data), 1)
        logger.debug("snapshot_compressed", original_bytes=len(data), compressed_bytes=len(compressed), ratio=ratio)
        return compressed

    @staticmethod
    def decompress(data: bytes) -> dict[str, Any]:
        """Decompresses gzip data and deserializes JSON."""
        decompressed = gzip.decompress(data)
        return orjson.loads(decompressed)
