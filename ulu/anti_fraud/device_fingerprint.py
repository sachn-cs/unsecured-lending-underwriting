"""Device fingerprinting for synthetic identity and account takeover detection.

Item 44 from production roadmap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ulu.infra.logging import logger


@dataclass
class DeviceFingerprint:
    """Represents a captured device fingerprint."""

    device_id: str
    ip_address: str
    user_agent: str
    borrower_id: str
    timestamp: str
    geo_hash: str = ""  # coarse geohash for privacy
    screen_resolution: str = ""
    os_family: str = ""
    browser_family: str = ""


class DeviceFingerprintService:
    """Tracks device fingerprints per borrower and flags anomalies.

    In production this should be backed by Redis/PostgreSQL for
    cross-instance consistency.
    """

    def __init__(self) -> None:
        self._fingerprints: dict[str, list[DeviceFingerprint]] = {}

    def record(
        self,
        borrower_id: str,
        device_id: str,
        ip_address: str,
        user_agent: str,
        timestamp: str,
        geo_hash: str = "",
        screen_resolution: str = "",
        os_family: str = "",
        browser_family: str = "",
    ) -> DeviceFingerprint:
        """Records a new fingerprint for a borrower."""
        fp = DeviceFingerprint(
            device_id=device_id,
            ip_address=ip_address,
            user_agent=user_agent,
            borrower_id=borrower_id,
            timestamp=timestamp,
            geo_hash=geo_hash,
            screen_resolution=screen_resolution,
            os_family=os_family,
            browser_family=browser_family,
        )
        self._fingerprints.setdefault(borrower_id, [])
        self._fingerprints[borrower_id].append(fp)
        logger.info(
            "device_fingerprint_recorded",
            borrower_id=borrower_id,
            device_id=device_id,
            ip_address=ip_address,
        )
        return fp

    def get_history(self, borrower_id: str) -> list[DeviceFingerprint]:
        """Returns all recorded fingerprints for a borrower."""
        return list(self._fingerprints.get(borrower_id, []))

    def is_new_device(self, borrower_id: str, device_id: str) -> bool:
        """Returns True if this device_id has not been seen for the borrower."""
        history = self._fingerprints.get(borrower_id, [])
        return not any(fp.device_id == device_id for fp in history)

    def is_suspicious_location_change(
        self,
        borrower_id: str,
        current_geo_hash: str,
        min_history: int = 2,
    ) -> bool:
        """Flags if current geohash differs from all historical ones.

        Uses coarse geohash (e.g., 4 characters ~ 20km) to avoid
        false positives on VPNs and travel.
        """
        if not current_geo_hash:
            return False
        history = self._fingerprints.get(borrower_id, [])
        if len(history) < min_history:
            return False
        past_hashes = {fp.geo_hash for fp in history if fp.geo_hash}
        return current_geo_hash not in past_hashes

    def detect_anomalies(
        self,
        borrower_id: str,
        device_id: str,
        ip_address: str,
        geo_hash: str = "",
    ) -> dict[str, Any]:
        """Runs all checks and returns anomaly flags."""
        new_device = self.is_new_device(borrower_id, device_id)
        location_change = self.is_suspicious_location_change(borrower_id, geo_hash)
        history = self.get_history(borrower_id)
        unique_devices = len({fp.device_id for fp in history})

        anomalies: list[dict[str, Any]] = []
        if new_device:
            anomalies.append(
                {"type": "new_device", "severity": "medium", "device_id": device_id}
            )
        if location_change:
            anomalies.append(
                {"type": "location_change", "severity": "low", "geo_hash": geo_hash}
            )
        if unique_devices > 5:
            anomalies.append(
                {
                    "type": "many_devices",
                    "severity": "high",
                    "unique_devices": unique_devices,
                }
            )

        logger.info(
            "device_fingerprint_anomalies_checked",
            borrower_id=borrower_id,
            anomalies=len(anomalies),
        )
        return {
            "borrower_id": borrower_id,
            "anomalies": anomalies,
            "new_device": new_device,
            "location_change": location_change,
            "unique_devices": unique_devices,
        }
