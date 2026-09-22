"""Authenticated free compute coordinator for remote lead-processing workers.

The coordinator is the only component that owns the shared task state. Remote
workers never open the coordinator SQLite database directly. The service uses
only the Python standard library and an operator-provided bearer token.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import ssl
import threading
import time
import uuid
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from .compute_fabric import ComputeFabricController, ComputeFabricOrchestrator
from .compute_inventory import ComputeInventory
from .compute_pool import ComputePool, WorkerIdentity
from .compute_provider import ProviderResourceSnapshot
from .compute_resources import ComputeRequirements, CpuResource, GpuResource, GpuRequirements, NodeResource, ResourceState, WorkloadClass
from .compute_scheduler import ComputeScheduler, ComputeSchedulingError
from .nvidia_runtime import NvidiaRuntime, NvidiaRuntimeError


class ComputeCoordinator:
    def __init__(self, db_path: str, auth_token: str, lease_seconds: int = 300, inventory: ComputeInventory | None = None):
        if not auth_token:
            raise ValueError("auth_token is required")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        self.db_path = db_path
        self.auth_token = auth_token
        self.pool = ComputePool(db_path, lease_seconds=lease_seconds)
        self.lease_seconds = lease_seconds
        inventory_path = os.environ.get("THORIO_COMPUTE_INVENTORY_DB", f"{db_path}.inventory.sqlite3")
        self.inventory = inventory or ComputeInventory(inventory_path)
        self.compute_scheduler = ComputeScheduler(self.inventory)
        self.compute_fabric = ComputeFabricOrchestrator(self.inventory, scheduler=self.compute_scheduler)
        self.compute_fabric_controller = ComputeFabricController(self)