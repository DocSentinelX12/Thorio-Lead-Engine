"""Zero-cost external compute acquisition boundary.

This module discovers and acquires only legitimately free/no-cost external
compute. It deliberately does not schedule workloads, own inventory, enroll
workers, or mutate business state. Successful acquisition returns an external
capacity handoff that must pass the existing authenticated worker enrollment
and physical discovery path before it can become trusted inventory.

Provider adapters are responsible for their own externally authorized API
interaction. Secrets and provider credentials remain outside durable acquisition
records.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any, Mapping


class FreeComputeAcquisitionError(RuntimeError):
    """Raised when a provider cannot satisfy the zero-cost acquisition contract."""


@dataclass(frozen=True)
class FreeComputeOffer:
    provider_id: str
    domain_id: str
    offer_id: str
    observed_at: float
    expires_at: float | None
    gpu_capable: bool
    no_cost: bool
    capacity_evidence: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.domain_id.strip() or not self.offer_id.strip():
            raise ValueError("provider_id, domain_id, and offer_id are required")
        if self.observed_at <= 0:
            raise ValueError("observed_at must be positive")
        if self.expires_at is not None and self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be later than observed_at")
        if not self.no_cost:
            raise ValueError("only no-cost offers may enter the free acquisition boundary")
        if not isinstance(self.capacity_evidence, Mapping) or not self.capacity_evidence:
            raise ValueError("capacity_evidence must contain observed provider evidence")


@dataclass(frozen=True)
class AcquiredCompute:
    provider_id: str
    domain_id: str
    offer_id: str
    acquisition_id: str
    acquired_at: float
    expires_at: float | None
    gpu_capable: bool
    enrollment: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.domain_id.strip() or not self.offer_id.strip() or not self.acquisition_id.strip():
            raise ValueError("complete acquisition identity is required")
        if self.acquired_at <= 0:
            raise ValueError("acquired_at must be positive")
        if self.expires_at is not None and self.expires_at <= self.acquired_at:
            raise ValueError("expires_at must be later than acquired_at")
        if not isinstance(self.enrollment, Mapping) or not self.enrollment:
            raise ValueError("successful acquisition must provide an enrollment handoff")


class FreeComputeProvider(ABC):
    """Provider adapter capable of discovering and acquiring free capacity."""

    provider_id: str

    @abstractmethod
    def discover_free(self) -> tuple[FreeComputeOffer, ...]:
        """Return currently observed eligible no-cost offers."""
        raise NotImplementedError

    @abstractmethod
    def acquire_free(self, offer: FreeComputeOffer) -> AcquiredCompute:
        """Acquire one offer through an externally authorized provider interface."""
        raise NotImplementedError

    def release_free(self, acquisition: AcquiredCompute) -> None:
        """Release capacity when the provider supports an explicit release operation."""
        return None


class FreeComputeAcquisitionStore:
    """Durable acquisition ledger; it is not a scheduler or resource inventory."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS compute_free_acquisitions (
                    acquisition_id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    domain_id TEXT NOT NULL,
                    offer_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    observed_at REAL NOT NULL,
                    acquired_at REAL,
                    expires_at REAL,
                    gpu_capable INTEGER NOT NULL,
                    no_cost INTEGER NOT NULL,
                    evidence_json TEXT NOT NULL,
                    enrollment_json TEXT,
                    verification_json TEXT NOT NULL DEFAULT '{}',
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                )"""
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_free_acquisition_offer "
                "ON compute_free_acquisitions(provider_id,domain_id,offer_id)"
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(compute_free_acquisitions)")}
            if "verification_json" not in columns:
                connection.execute("ALTER TABLE compute_free_acquisitions ADD COLUMN verification_json TEXT NOT NULL DEFAULT '{}'")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_free_acquisition_status "
                "ON compute_free_acquisitions(status,updated_at)"
            )
            connection.commit()

    @staticmethod
    def acquisition_id(offer: FreeComputeOffer) -> str:
        raw = f"{offer.provider_id}\x00{offer.domain_id}\x00{offer.offer_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def record_offer(self, offer: FreeComputeOffer) -> str:
        acquisition_id = self.acquisition_id(offer)
        now = time.time()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT acquisition_id,no_cost,evidence_json FROM compute_free_acquisitions "
                "WHERE provider_id=? AND domain_id=? AND offer_id=?",
                (offer.provider_id, offer.domain_id, offer.offer_id),
            ).fetchone()
            evidence = json.dumps(dict(offer.capacity_evidence), sort_keys=True, ensure_ascii=False)
            if existing:
                if int(existing["no_cost"]) != 1:
                    raise FreeComputeAcquisitionError("existing acquisition record violates zero-cost policy")
                connection.execute(
                    """UPDATE compute_free_acquisitions
                       SET observed_at=?,expires_at=?,gpu_capable=?,evidence_json=?,updated_at=?
                       WHERE acquisition_id=?""",
                    (offer.observed_at, offer.expires_at, int(offer.gpu_capable), evidence, now, existing["acquisition_id"]),
                )
                connection.commit()
                return str(existing["acquisition_id"])
            connection.execute(
                """INSERT INTO compute_free_acquisitions
                   (acquisition_id,provider_id,domain_id,offer_id,status,observed_at,expires_at,
                    gpu_capable,no_cost,evidence_json,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (acquisition_id, offer.provider_id, offer.domain_id, offer.offer_id, "discovered",
                 offer.observed_at, offer.expires_at, int(offer.gpu_capable), 1, evidence, now),
            )
            connection.commit()
        return acquisition_id

    def mark_acquired(self, acquired: AcquiredCompute, offer: FreeComputeOffer) -> None:
        expected = self.acquisition_id(offer)
        if acquired.acquisition_id != expected:
            raise FreeComputeAcquisitionError("acquisition identity does not match observed offer")
        if acquired.provider_id != offer.provider_id or acquired.domain_id != offer.domain_id or acquired.offer_id != offer.offer_id:
            raise FreeComputeAcquisitionError("acquisition identity does not match observed offer")
        enrollment = json.dumps(dict(acquired.enrollment), sort_keys=True, ensure_ascii=False)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT no_cost FROM compute_free_acquisitions WHERE acquisition_id=?",
                (expected,),
            ).fetchone()
            if row is None:
                raise FreeComputeAcquisitionError("offer must be durably recorded before acquisition")
            if int(row["no_cost"]) != 1:
                raise FreeComputeAcquisitionError("paid acquisition is permanently forbidden")
            connection.execute(
                """UPDATE compute_free_acquisitions
                   SET status='acquired',acquired_at=?,expires_at=?,gpu_capable=?,
                       enrollment_json=?,last_error='',updated_at=?
                   WHERE acquisition_id=?""",
                (acquired.acquired_at, acquired.expires_at, int(acquired.gpu_capable),
                 enrollment, time.time(), expected),
            )
            connection.commit()

    def mark_worker_verified(
        self,
        acquisition_id: str,
        *,
        worker_id: str,
        verification: Mapping[str, Any],
    ) -> bool:
        """Promote an acquired offer only after authenticated worker physical evidence."""
        key = str(acquisition_id).strip()
        worker = str(worker_id).strip()
        if not key or not worker:
            raise FreeComputeAcquisitionError("acquisition_id and worker_id are required")
        if not isinstance(verification, Mapping) or not verification:
            raise FreeComputeAcquisitionError("worker verification evidence is required")
        gpu_capable = bool(verification.get("gpu_capable"))
        discovery_state = str(verification.get("gpu_discovery_state") or "").strip()
        physical = verification.get("physical_fabric_evidence")
        gpu_resources = verification.get("gpu_resources")
        if not isinstance(physical, Mapping) or not physical:
            raise FreeComputeAcquisitionError("physical hardware evidence is required before trust")
        if gpu_capable:
            if discovery_state != "healthy":
                raise FreeComputeAcquisitionError("GPU acquisition requires healthy worker-local GPU discovery")
            if not isinstance(gpu_resources, (list, tuple)) or not gpu_resources:
                raise FreeComputeAcquisitionError("GPU acquisition requires observed GPU resources")
            for gpu in gpu_resources:
                if not isinstance(gpu, Mapping) or not str(gpu.get("gpu_uuid") or "").strip():
                    raise FreeComputeAcquisitionError("GPU acquisition requires stable observed GPU UUIDs")
        verification_payload = dict(verification)
        verification_payload["worker_id"] = worker
        payload = json.dumps(verification_payload, sort_keys=True, ensure_ascii=False)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status,no_cost,gpu_capable FROM compute_free_acquisitions WHERE acquisition_id=?",
                (key,),
            ).fetchone()
            if row is None:
                raise FreeComputeAcquisitionError("acquisition must be durably recorded before enrollment")
            if int(row["no_cost"]) != 1:
                raise FreeComputeAcquisitionError("paid acquisition is permanently forbidden")
            if int(row["gpu_capable"]) == 1 and not gpu_capable:
                raise FreeComputeAcquisitionError("GPU acquisition cannot be verified as CPU-only")
            if row["status"] == "verified":
                return True
            if row["status"] != "acquired":
                raise FreeComputeAcquisitionError(f"acquisition is not awaiting physical enrollment: {row['status']}")
            connection.execute(
                """UPDATE compute_free_acquisitions
                   SET status='verified',verification_json=?,last_error='',updated_at=?
                   WHERE acquisition_id=? AND status='acquired'""",
                (payload, time.time(), key),
            )
            connection.commit()
        return True

    def mark_retry(self, acquisition_id: str, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE compute_free_acquisitions
                   SET status='retry_pending',last_error=?,updated_at=?
                   WHERE acquisition_id=?""",
                (str(error)[:4000], time.time(), acquisition_id),
            )
            connection.commit()

    def mark_released(self, acquisition_id: str, reason: str = "") -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE compute_free_acquisitions
                   SET status='released',last_error=?,updated_at=?
                   WHERE acquisition_id=?""",
                (str(reason)[:4000], time.time(), acquisition_id),
            )
            connection.commit()

    def records(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM compute_free_acquisitions ORDER BY updated_at,acquisition_id"
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            item["enrollment"] = json.loads(item.pop("enrollment_json")) if item.get("enrollment_json") else None
            item["verification"] = json.loads(item.pop("verification_json") or "{}")
            item["worker_id"] = item["verification"].get("worker_id") if isinstance(item["verification"], dict) else None
            item["no_cost"] = bool(item["no_cost"])
            item["gpu_capable"] = bool(item["gpu_capable"])
            item.pop("enrollment_json", None)
            result.append(item)
        return result


class FreeComputeAcquisitionManager:
    """Discover/acquire free capacity and hand it to the existing enrollment path."""

    def __init__(self, store: FreeComputeAcquisitionStore, *, clock=time.time):
        self.store = store
        self._clock = clock
        self._providers: dict[str, FreeComputeProvider] = {}

    def register(self, provider: FreeComputeProvider) -> None:
        provider_id = str(provider.provider_id).strip()
        if not provider_id:
            raise ValueError("provider_id is required")
        if provider_id in self._providers:
            raise ValueError(f"free compute provider already registered: {provider_id}")
        self._providers[provider_id] = provider

    def providers(self) -> tuple[FreeComputeProvider, ...]:
        return tuple(self._providers[key] for key in sorted(self._providers))

    def discover(self) -> dict[str, Any]:
        offers: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for provider_id, provider in sorted(self._providers.items()):
            try:
                observed = provider.discover_free()
                for offer in observed:
                    if offer.provider_id != provider_id:
                        raise FreeComputeAcquisitionError("provider identity mismatch in free offer")
                    if not offer.no_cost:
                        raise FreeComputeAcquisitionError("provider returned a paid offer to the free boundary")
                    self.store.record_offer(offer)
                    offers.append(asdict(offer))
            except Exception as exc:
                errors.append({"provider_id": provider_id, "error": f"{type(exc).__name__}: {exc}"})
        return {"offers": tuple(offers), "errors": tuple(errors), "provider_count": len(self._providers)}

    def acquire(self, offer: FreeComputeOffer) -> AcquiredCompute:
        if not offer.no_cost:
            raise FreeComputeAcquisitionError("paid capacity is permanently forbidden")
        if offer.expires_at is not None and offer.expires_at <= self._clock():
            raise FreeComputeAcquisitionError("free compute offer is expired")
        provider = self._providers.get(offer.provider_id)
        if provider is None:
            raise FreeComputeAcquisitionError(f"free compute provider is not registered: {offer.provider_id}")
        acquisition_id = self.store.record_offer(offer)
        try:
            acquired = provider.acquire_free(offer)
            if acquired.acquisition_id != acquisition_id:
                raise FreeComputeAcquisitionError("provider returned an unexpected acquisition identity")
            if acquired.provider_id != offer.provider_id or acquired.domain_id != offer.domain_id or acquired.offer_id != offer.offer_id:
                raise FreeComputeAcquisitionError("provider returned mismatched acquisition identity")
            self.store.mark_acquired(acquired, offer)
            return acquired
        except Exception as exc:
            self.store.mark_retry(acquisition_id, f"{type(exc).__name__}: {exc}")
            raise

    def confirm_worker_enrollment(
        self,
        *,
        acquisition_id: str,
        worker_id: str,
        verification: Mapping[str, Any],
    ) -> bool:
        """Bind an acquired offer to authenticated worker and physical evidence."""
        return self.store.mark_worker_verified(
            acquisition_id,
            worker_id=worker_id,
            verification=verification,
        )

    def release(self, acquisition: AcquiredCompute) -> None:
        provider = self._providers.get(acquisition.provider_id)
        if provider is None:
            raise FreeComputeAcquisitionError(f"free compute provider is not registered: {acquisition.provider_id}")
        provider.release_free(acquisition)
        self.store.mark_released(acquisition.acquisition_id)

    def status(self) -> dict[str, Any]:
        records = self.store.records()
        return {
            "provider_count": len(self._providers),
            "records": tuple(records),
            "free_only": True,
            "paid_capacity_allowed": False,
            "acquired_unverified_count": sum(1 for item in records if item["status"] == "acquired"),
            "eligible_acquired_count": sum(1 for item in records if item["status"] == "verified"),
            "eligible_verified_count": sum(1 for item in records if item["status"] == "verified"),
        }
