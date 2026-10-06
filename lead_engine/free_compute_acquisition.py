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

from .compute_fabric import ProviderCapabilities


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

    def capabilities(self) -> ProviderCapabilities:
        """Return adapter capabilities; physical execution remains separately attested."""
        return ProviderCapabilities()

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

    def acquisition_status(self, acquisition: AcquiredCompute) -> str | None:
        """Return provider-observed lifecycle state for a durable acquisition."""
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
        if acquired.acquired_at < offer.observed_at:
            raise FreeComputeAcquisitionError("acquisition cannot predate the observed offer")
        if offer.expires_at is not None:
            if acquired.expires_at is None or acquired.expires_at > offer.expires_at:
                raise FreeComputeAcquisitionError("acquisition expiry cannot extend beyond the observed offer")
            if acquired.acquired_at >= offer.expires_at:
                raise FreeComputeAcquisitionError("acquisition must begin before the observed offer expires")
        if acquired.gpu_capable and not offer.gpu_capable:
            raise FreeComputeAcquisitionError("acquisition cannot claim GPU capability absent from the observed offer")
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
            physical_execution = verification.get("physical_gpu_execution")
            if not isinstance(physical_execution, (list, tuple)) or len(physical_execution) != len(gpu_resources):
                raise FreeComputeAcquisitionError("GPU acquisition requires physical CUDA execution evidence for every observed GPU")
            observed_uuids = {
                str(gpu.get("gpu_uuid") or "").strip()
                for gpu in gpu_resources
                if isinstance(gpu, Mapping)
            }
            executed_uuids = {
                str(item.get("gpu_uuid") or "").strip()
                for item in physical_execution
                if isinstance(item, Mapping)
            }
            if executed_uuids != observed_uuids:
                raise FreeComputeAcquisitionError("GPU execution evidence does not match observed physical GPU identities")
            for item in physical_execution:
                if (
                    not isinstance(item, Mapping)
                    or item.get("verified") is not True
                    or str(item.get("execution_backend") or "").strip().lower() != "cuda"
                    or not str(item.get("operation") or "").strip()
                    or not isinstance(item.get("checksum"), (int, float))
                    or not isinstance(item.get("elapsed_ms"), (int, float))
                    or float(item.get("elapsed_ms", -1)) < 0
                ):
                    raise FreeComputeAcquisitionError("GPU acquisition requires verified CUDA execution evidence")
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

    @staticmethod
    def _provider_key(provider: FreeComputeProvider) -> str:
        provider_id = str(provider.provider_id).strip()
        if not provider_id:
            raise ValueError("provider_id is required")
        domain_id = ""
        domain_method = getattr(provider, "_domain_id", None)
        if callable(domain_method):
            try:
                domain_id = str(domain_method()).strip()
            except Exception:
                domain_id = ""
        config = getattr(provider, "config", None)
        if not domain_id and config is not None:
            username = str(getattr(config, "username", "")).strip()
            kernel_slug = str(getattr(config, "kernel_slug", "")).strip()
            if username and kernel_slug:
                domain_id = f"{provider_id}:{username}:{kernel_slug}"
        if not domain_id:
            return provider_id
        return f"{provider_id}:{domain_id}"

    def register(self, provider: FreeComputeProvider) -> None:
        key = self._provider_key(provider)
        if key in self._providers:
            raise ValueError(f"free compute provider already registered: {key}")
        self._providers[key] = provider

    def providers(self) -> tuple[FreeComputeProvider, ...]:
        return tuple(self._providers[key] for key in sorted(self._providers))

    def provider_capabilities(self) -> dict[str, dict[str, Any]]:
        """Return registered adapter capabilities without inventing capacity."""
        return {
            key: provider.capabilities().to_dict()
            for key, provider in sorted(self._providers.items())
        }

    def discover(self) -> dict[str, Any]:
        offers: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for provider_key, provider in sorted(self._providers.items()):
            provider_id = str(provider.provider_id).strip()
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
                errors.append({"provider_id": provider_id, "provider_key": provider_key, "error": f"{type(exc).__name__}: {exc}"})
        return {
            "offers": tuple(offers),
            "errors": tuple(errors),
            "provider_count": len(self._providers),
            "provider_ids": tuple(sorted({str(provider.provider_id).strip() for provider in self._providers.values()})),
        }

    def compatible_provider_ids(self, required_capabilities: Mapping[str, bool] | None = None) -> tuple[str, ...]:
        """Return registered providers whose declared capabilities satisfy a job."""
        required = dict(required_capabilities or {})
        compatible: list[str] = []
        for key, provider in sorted(self._providers.items()):
            missing = provider.capabilities().missing(required)
            if not missing:
                compatible.append(key)
        return tuple(compatible)

    def acquire_for_requirements(
        self,
        *,
        required_capabilities: Mapping[str, bool] | None = None,
        gpu_required: bool = False,
    ) -> dict[str, Any]:
        """Discover and acquire the first deterministic offer satisfying requirements."""
        required = dict(required_capabilities or {})
        provider_keys = set(self.compatible_provider_ids(required))
        if not provider_keys:
            return {
                "acquired": None,
                "provider_candidates": (),
                "offers_observed": 0,
                "errors": (),
                "status": "no_compatible_provider",
            }

        discovery = self.discover()
        errors = list(discovery["errors"])
        candidates = []
        for offer_data in discovery["offers"]:
            offer = FreeComputeOffer(**offer_data)
            key = self._provider_key_for_offer(offer)
            if key not in provider_keys:
                continue
            if gpu_required and not offer.gpu_capable:
                continue
            candidates.append(offer)

        for offer in sorted(candidates, key=lambda item: (item.provider_id, item.domain_id, item.offer_id)):
            try:
                acquired = self.acquire(offer)
                return {
                    "acquired": asdict(acquired),
                    "provider_candidates": tuple(sorted(provider_keys)),
                    "offers_observed": len(candidates),
                    "errors": tuple(errors),
                    "status": "acquired",
                }
            except Exception as exc:
                errors.append({
                    "provider_id": offer.provider_id,
                    "offer_id": offer.offer_id,
                    "error": f"{type(exc).__name__}: {exc}",
                })
        return {
            "acquired": None,
            "provider_candidates": tuple(sorted(provider_keys)),
            "offers_observed": len(candidates),
            "errors": tuple(errors),
            "status": "acquisition_failed",
        }

    def _provider_key_for_offer(self, offer: FreeComputeOffer) -> str:
        exact = f"{offer.provider_id}:{offer.domain_id}"
        if exact in self._providers:
            return exact
        matching = [
            key for key, provider in self._providers.items()
            if str(provider.provider_id).strip() == str(offer.provider_id).strip()
        ]
        if len(matching) == 1:
            return matching[0]
        return exact

    def acquire(self, offer: FreeComputeOffer) -> AcquiredCompute:
        if not offer.no_cost:
            raise FreeComputeAcquisitionError("paid capacity is permanently forbidden")
        if offer.expires_at is not None and offer.expires_at <= self._clock():
            raise FreeComputeAcquisitionError("free compute offer is expired")
        matching = [
            candidate
            for candidate in self._providers.values()
            if str(candidate.provider_id).strip() == offer.provider_id
        ]
        exact = [
            candidate
            for candidate in matching
            if self._provider_key(candidate) == f"{offer.provider_id}:{offer.domain_id}"
        ]
        if len(exact) == 1:
            provider = exact[0]
        elif len(matching) == 1:
            # Backward-compatible provider adapters may expose a single
            # provider-wide identity rather than a domain method. The offer
            # remains the authoritative domain identity in the durable ledger.
            provider = matching[0]
        else:
            raise FreeComputeAcquisitionError(
                f"free compute provider domain is not registered: {offer.provider_id}:{offer.domain_id}"
            )
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

    def handoff_acquired(
        self,
        *,
        offer: FreeComputeOffer,
        acquired: AcquiredCompute,
    ) -> AcquiredCompute:
        """Durably import an already-acquired free offer into the coordinator ledger.

        The external acquisition may be performed by a CI control-plane host, but
        the coordinator must own the authoritative durable record before worker
        enrollment can succeed. This handoff never promotes hardware to trusted
        inventory; physical worker verification remains a separate gate.
        """
        if not offer.no_cost:
            raise FreeComputeAcquisitionError("paid capacity is permanently forbidden")
        expected = self.store.acquisition_id(offer)
        if acquired.acquisition_id != expected:
            raise FreeComputeAcquisitionError("acquisition identity does not match observed offer")
        if acquired.provider_id != offer.provider_id or acquired.domain_id != offer.domain_id or acquired.offer_id != offer.offer_id:
            raise FreeComputeAcquisitionError("acquisition identity does not match observed offer")
        if offer.expires_at is not None and acquired.acquired_at >= offer.expires_at:
            raise FreeComputeAcquisitionError("acquisition must begin before the observed offer expires")
        existing = next(
            (item for item in self.store.records() if str(item.get("acquisition_id")) == expected),
            None,
        )
        if existing is not None:
            status = str(existing.get("status") or "")
            if status in {"acquired", "verified"}:
                return acquired
            if status == "released":
                raise FreeComputeAcquisitionError("released acquisition cannot be reactivated")
        self.store.record_offer(offer)
        self.store.mark_acquired(acquired, offer)
        return acquired

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

    def _provider_for_acquisition(self, acquisition: AcquiredCompute) -> FreeComputeProvider:
        provider_id = str(acquisition.provider_id).strip()
        domain_id = str(acquisition.domain_id).strip()
        exact_key = f"{provider_id}:{domain_id}"
        provider = self._providers.get(exact_key)
        if provider is None:
            matching = [
                candidate
                for candidate in self._providers.values()
                if str(candidate.provider_id).strip() == provider_id
            ]
            if len(matching) == 1:
                provider = matching[0]
        if provider is None:
            raise FreeComputeAcquisitionError(
                f"free compute provider domain is not registered: {provider_id}:{domain_id}"
            )
        return provider

    @staticmethod
    def _record_as_acquisition(record: Mapping[str, Any]) -> AcquiredCompute:
        acquired_at = record.get("acquired_at")
        if acquired_at is None:
            raise FreeComputeAcquisitionError("active acquisition record is missing acquired_at")
        return AcquiredCompute(
            provider_id=str(record["provider_id"]),
            domain_id=str(record["domain_id"]),
            offer_id=str(record["offer_id"]),
            acquisition_id=str(record["acquisition_id"]),
            acquired_at=float(acquired_at),
            expires_at=float(record["expires_at"]) if record.get("expires_at") is not None else None,
            gpu_capable=bool(record["gpu_capable"]),
            enrollment=record.get("enrollment") or {"worker_id": str(record.get("worker_id") or "")},
        )

    def reconcile(self) -> dict[str, Any]:
        """Reconcile durable active acquisitions with provider-observed state."""
        reconciled: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        terminal = {"complete", "failed", "cancelled", "not_found", "expired"}
        for record in self.store.records():
            if str(record["status"]) not in {"acquired", "verified"}:
                continue
            try:
                acquisition = self._record_as_acquisition(record)
                provider = self._provider_for_acquisition(acquisition)
                observed = provider.acquisition_status(acquisition)
                if observed is None or observed in {"running", "queued"}:
                    continue
                if observed not in terminal:
                    continue
                cleanup_error = ""
                try:
                    provider.release_free(acquisition)
                except Exception as exc:
                    cleanup_error = f"; cleanup failed: {type(exc).__name__}: {exc}"
                self.store.mark_released(acquisition.acquisition_id, f"provider lifecycle state: {observed}{cleanup_error}")
                reconciled.append({
                    "acquisition_id": acquisition.acquisition_id,
                    "provider_id": acquisition.provider_id,
                    "provider_state": observed,
                    "cleanup_error": cleanup_error,
                })
            except Exception as exc:
                errors.append({
                    "acquisition_id": str(record.get("acquisition_id") or ""),
                    "provider_id": str(record.get("provider_id") or ""),
                    "error": f"{type(exc).__name__}: {exc}",
                })
        return {"reconciled": tuple(reconciled), "errors": tuple(errors)}

    def release(self, acquisition: AcquiredCompute) -> None:
        provider = self._provider_for_acquisition(acquisition)
        provider.release_free(acquisition)
        self.store.mark_released(acquisition.acquisition_id)

    def status(self) -> dict[str, Any]:
        records = self.store.records()
        now = self._clock()

        def active(item: Mapping[str, Any]) -> bool:
            expires_at = item.get("expires_at")
            return expires_at is None or float(expires_at) > now

        acquired = [
            item for item in records
            if item["status"] == "acquired" and active(item)
        ]
        verified = [item for item in records if item["status"] == "verified"]
        eligible = [item for item in verified if active(item)]
        expired_verified = [item for item in verified if not active(item)]
        return {
            "provider_count": len(self._providers),
            "provider_ids": tuple(sorted({str(provider.provider_id).strip() for provider in self._providers.values()})),
            "records": tuple(records),
            "free_only": True,
            "paid_capacity_allowed": False,
            "acquired_unverified_count": sum(
                1 for item in records
                if item["status"] == "acquired" and active(item)
            ),
            "expired_acquired_count": sum(
                1 for item in records
                if item["status"] == "acquired" and not active(item)
            ),
            "eligible_acquired_count": len(eligible),
            "eligible_verified_count": len(eligible),
            "expired_verified_count": len(expired_verified),
        }


    def hunt_once(self) -> dict[str, Any]:
        """Perform one complete discovery/acquisition sweep across every provider.

        A provider failure is isolated to that provider. The sweep continues so
        one unavailable source can never suppress capacity from other sources.
        """
        reconciliation = self.reconcile()
        discovery = self.discover()
        acquired: list[dict[str, Any]] = []
        errors = list(reconciliation["errors"]) + list(discovery["errors"])
        durable = {
            str(item["acquisition_id"]): str(item["status"])
            for item in self.store.records()
            if str(item["status"]) in {"acquired", "verified"}
        }
        for offer_data in discovery["offers"]:
            offer = FreeComputeOffer(**offer_data)
            acquisition_id = self.store.acquisition_id(offer)
            if acquisition_id in durable:
                continue
            try:
                result = self.acquire(offer)
                acquired.append(asdict(result))
            except Exception as exc:
                errors.append(
                    {
                        "provider_id": offer.provider_id,
                        "offer_id": offer.offer_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return {
            "provider_count": discovery["provider_count"],
            "offers_observed": len(discovery["offers"]),
            "reconciled_count": len(reconciliation["reconciled"]),
            "acquired_count": len(acquired),
            "acquired": tuple(acquired),
            "errors": tuple(errors),
        }

    def run_continuously(
        self,
        *,
        interval_seconds: float,
        sleep=time.sleep,
        on_cycle=None,
    ) -> None:
        """Continuously hunt for free capacity until the host stops the loop.

        The first hunt is immediate. Subsequent hunts wait exactly the requested
        interval. Provider errors are returned in each cycle and never terminate
        the loop. The host process remains responsible for graceful shutdown.
        """
        interval = float(interval_seconds)
        if interval <= 0:
            raise ValueError("interval_seconds must be positive")
        while True:
            result = self.hunt_once()
            if on_cycle is not None:
                on_cycle(result)
            sleep(interval)
