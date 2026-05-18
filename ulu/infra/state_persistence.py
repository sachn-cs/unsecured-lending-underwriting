"""State persistence adapter decoupling filesystem I/O from domain core.

Item 85 from production roadmap.
"""

from __future__ import annotations

from pathlib import Path

import orjson

from ulu.core.serialization import SerializationMixin
from ulu.errors import ProtocolError


class StatePersistenceAdapter:
    """Handles saving and loading protocol state to/from JSON files.

    Extracts filesystem concerns from the core domain so that
    DelegatedUnderwriting remains pure in-memory logic.
    """

    @staticmethod
    def save_json(instance: SerializationMixin, path: str | Path) -> None:
        """Writes state payload to a JSON file using orjson."""
        target = Path(path)
        payload = orjson.dumps(
            instance.to_dict(),
            option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS,
        ).decode("utf-8")
        try:
            target.write_text(payload, encoding="utf-8")
        except OSError as exc:
            raise ProtocolError(f"failed to save state to {target}: {exc}") from exc

    @classmethod
    def load_json(cls, path: str | Path, target_class: type[SerializationMixin]):
        """Loads a mechanism instance from JSON state file using orjson."""
        target = Path(path)
        try:
            raw = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProtocolError(f"failed to load state from {target}: {exc}") from exc
        try:
            payload = orjson.loads(raw)
        except orjson.JSONDecodeError as exc:
            raise ProtocolError(f"invalid JSON in state file {target}: {exc}") from exc
        return target_class.from_dict(payload)
