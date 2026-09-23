from __future__ import annotations

import time

import pytest

from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.compute_resources import (
    ComputeRequirements,
    CpuResource,
    GpuRequirements,
    GpuResource,
    NodeResource,
    ResourceState,
    WorkloadClass,
)
from lead_engine.compute_scheduler import ComputeScheduler, ComputeSchedulingError
from lead_engine.physical_fabric import FabricPathState, FabricVerificationResult, PhysicalFabricPathBuilder, PhysicalFabricVerification
