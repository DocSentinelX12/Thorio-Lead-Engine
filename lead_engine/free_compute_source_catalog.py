"""Research-backed catalog of legitimate zero-cost external compute sources.

This module is intentionally additive. It does not replace the existing free
compute acquisition boundary, scheduler, worker enrollment, or physical
verification path. It records which external sources are actually compatible
with an unaffiliated operator and which are excluded by cost, eligibility, or
execution restrictions.

Only sources that can be used without paying money are marked zero_cost=True.
Temporary/shared notebook capacity is never represented as a persistent runner
or physical-fabric guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class ComputeSourceKind(str, Enum):
    GPU_RUNTIME = "gpu_runtime"
    GPU_NOTEBOOK = "gpu_notebook"
    SERVERLESS_GPU = "serverless_gpu"
    CPU_RUNTIME = "cpu_runtime"
    RESEARCH_ALLOCATION = "research_allocation"
    CREDIT_GRANT = "credit_grant"


class Eligibility(str, Enum):
    INDIVIDUAL = "individual"
    INSTITUTION_REQUIRED = "institution_required"
    STARTUP_REQUIRED = "startup_required"
    UNCERTAIN = "uncertain"


class FabricSuitability(str, Enum):
    DIRECT_RUNNER = "direct_runner"
    EPHEMERAL_EXECUTION = "ephemeral_execution"
    DISCOVERY_OR_PROOF_ONLY = "discovery_or_proof_only"
    NOT_A_FABRIC_RUNNER = "not_a_fabric_runner"


@dataclass(frozen=True)
class FreeComputeSource:
    source_id: str
    display_name: str
    kind: ComputeSourceKind
    eligibility: Eligibility
    zero_cost: bool
    gpu: bool
    cuda: bool
    persistent_runner: bool
    multi_gpu: bool
    multi_node: bool
    network_control: bool
    fabric_suitability: FabricSuitability
    requires_payment_method: bool
    requires_institution: bool
    requires_startup_status: bool
    account_age_or_verification: str | None
    documented_limits: str
    official_url: str
    notes: str


# These entries are deliberately conservative. A source is not promoted to
# direct-runner status merely because it exposes a GPU. Provider terms and the
# execution surface must support the actual role.
FREE_COMPUTE_SOURCES: tuple[FreeComputeSource, ...] = (
    FreeComputeSource(
        source_id="paperspace_gradient_free_gpu",
        display_name="Paperspace Gradient Free GPU",
        kind=ComputeSourceKind.GPU_NOTEBOOK,
        eligibility=Eligibility.INDIVIDUAL,
        zero_cost=True,
        gpu=True,
        cuda=True,
        persistent_runner=False,
        multi_gpu=False,
        multi_node=False,
        network_control=False,
        fabric_suitability=FabricSuitability.EPHEMERAL_EXECUTION,
        requires_payment_method=False,
        requires_institution=False,
        requires_startup_status=False,
        account_age_or_verification=None,
        documented_limits="Free CPU and GPU instance types; notebook-oriented execution.",
        official_url="https://ml-showcase.paperspace.com/guide",
        notes="Useful for real GPU execution and capability probing, but not a persistent self-hosted runner.",
    ),
    FreeComputeSource(
        source_id="kaggle_notebooks_gpu",
        display_name="Kaggle Notebooks GPU",
        kind=ComputeSourceKind.GPU_NOTEBOOK,
        eligibility=Eligibility.INDIVIDUAL,
        zero_cost=True,
        gpu=True,
        cuda=True,
        persistent_runner=False,
        multi_gpu=True,
        multi_node=False,
        network_control=False,
        fabric_suitability=FabricSuitability.EPHEMERAL_EXECUTION,
        requires_payment_method=False,
        requires_institution=False,
        requires_startup_status=False,
        account_age_or_verification=None,
        documented_limits="P100 or T4 x2 notebook environments; sessions are time/quota limited.",
        official_url="https://www.kaggle.com/docs/notebooks",
        notes="Real NVIDIA compute. Suitable for physical CUDA probing and bounded workloads, not an always-on runner.",
    ),
    FreeComputeSource(
        source_id="huggingface_zerogpu",
        display_name="Hugging Face ZeroGPU",
        kind=ComputeSourceKind.SERVERLESS_GPU,
        eligibility=Eligibility.INDIVIDUAL,
        zero_cost=True,
        gpu=True,
        cuda=True,
        persistent_runner=False,
        multi_gpu=True,
        multi_node=False,
        network_control=False,
        fabric_suitability=FabricSuitability.EPHEMERAL_EXECUTION,
        requires_payment_method=False,
        requires_institution=False,
        requires_startup_status=False,
        account_age_or_verification="Free personal account in good standing; verified email and account age requirements for hosting.",
        documented_limits="Free account has a documented daily GPU quota and ZeroGPU is Gradio/Space based.",
        official_url="https://huggingface.co/docs/hub/main/spaces-zerogpu",
        notes="Actual RTX Pro 6000 Blackwell-backed shared GPU execution, but quota-based and not a persistent runner.",
    ),
    FreeComputeSource(
        source_id="google_colab_free",
        display_name="Google Colab Free GPU",
        kind=ComputeSourceKind.GPU_NOTEBOOK,
        eligibility=Eligibility.INDIVIDUAL,
        zero_cost=True,
        gpu=True,
        cuda=True,
        persistent_runner=False,
        multi_gpu=False,
        multi_node=False,
        network_control=False,
        fabric_suitability=FabricSuitability.DISCOVERY_OR_PROOF_ONLY,
        requires_payment_method=False,
        requires_institution=False,
        requires_startup_status=False,
        account_age_or_verification=None,
        documented_limits="Free managed runtimes have variable availability and session limits.",
        official_url="https://developers.google.com/colab",
        notes="Useful as an individual GPU execution source, but managed-runtime restrictions make it unsuitable as a Thorio distributed runner.",
    ),
    FreeComputeSource(
        source_id="modal_starter_free_compute",
        display_name="Modal Starter Included Compute",
        kind=ComputeSourceKind.SERVERLESS_GPU,
        eligibility=Eligibility.INDIVIDUAL,
        zero_cost=True,
        gpu=True,
        cuda=True,
        persistent_runner=False,
        multi_gpu=True,
        multi_node=True,
        network_control=False,
        fabric_suitability=FabricSuitability.EPHEMERAL_EXECUTION,
        requires_payment_method=True,
        requires_institution=False,
        requires_startup_status=False,
        account_age_or_verification=None,
        documented_limits="$30/month included compute, after which usage is billable; payment-method requirement must be satisfied before treating it as usable.",
        official_url="https://modal.com/pricing",
        notes="Catalogued for completeness but blocked by the project's no-payment-method rule unless Modal explicitly permits an account without one.",
    ),
    FreeComputeSource(
        source_id="access_jetstream2",
        display_name="ACCESS Jetstream2",
        kind=ComputeSourceKind.RESEARCH_ALLOCATION,
        eligibility=Eligibility.INSTITUTION_REQUIRED,
        zero_cost=True,
        gpu=True,
        cuda=True,
        persistent_runner=True,
        multi_gpu=True,
        multi_node=True,
        network_control=True,
        fabric_suitability=FabricSuitability.DIRECT_RUNNER,
        requires_payment_method=False,
        requires_institution=True,
        requires_startup_status=False,
        account_age_or_verification="Current ACCESS eligibility rules apply.",
        documented_limits="Allocation and eligibility controlled; not an immediately available unaffiliated-user resource.",
        official_url="https://docs.jetstream-cloud.org/general/vmsizes/",
        notes="Technically strong runner target, but intentionally excluded from immediate acquisition for an unaffiliated individual.",
    ),
    FreeComputeSource(
        source_id="national_research_platform",
        display_name="National Research Platform / Nautilus",
        kind=ComputeSourceKind.RESEARCH_ALLOCATION,
        eligibility=Eligibility.INSTITUTION_REQUIRED,
        zero_cost=True,
        gpu=True,
        cuda=True,
        persistent_runner=True,
        multi_gpu=True,
        multi_node=True,
        network_control=True,
        fabric_suitability=FabricSuitability.DIRECT_RUNNER,
        requires_payment_method=False,
        requires_institution=True,
        requires_startup_status=False,
        account_age_or_verification="U.S. nonprofit/research/education eligibility applies.",
        documented_limits="Shared Kubernetes infrastructure with opportunistic/preemptible capacity.",
        official_url="https://nrp.ai/",
        notes="Excellent architectural fit if legitimate eligibility becomes available; not claimed as immediately accessible to an unaffiliated individual.",
    ),
    FreeComputeSource(
        source_id="osg_open_science_pool",
        display_name="Open Science Grid / Open Science Pool",
        kind=ComputeSourceKind.RESEARCH_ALLOCATION,
        eligibility=Eligibility.INSTITUTION_REQUIRED,
        zero_cost=True,
        gpu=True,
        cuda=True,
        persistent_runner=False,
        multi_gpu=True,
        multi_node=False,
        network_control=False,
        fabric_suitability=FabricSuitability.EPHEMERAL_EXECUTION,
        requires_payment_method=False,
        requires_institution=True,
        requires_startup_status=False,
        account_age_or_verification="Research-community access requirements apply.",
        documented_limits="High-throughput opportunistic execution; tightly coupled inter-node workloads are not its primary use case.",
        official_url="https://osg-htc.org/",
        notes="Potential large opportunistic capacity pool, but not the authoritative physical NCCL fabric.",
    ),
    FreeComputeSource(
        source_id="nvidia_inception_partner_credits",
        display_name="NVIDIA Inception Partner Credits",
        kind=ComputeSourceKind.CREDIT_GRANT,
        eligibility=Eligibility.STARTUP_REQUIRED,
        zero_cost=True,
        gpu=True,
        cuda=True,
        persistent_runner=True,
        multi_gpu=True,
        multi_node=True,
        network_control=True,
        fabric_suitability=FabricSuitability.DIRECT_RUNNER,
        requires_payment_method=False,
        requires_institution=False,
        requires_startup_status=True,
        account_age_or_verification="Program acceptance required.",
        documented_limits="Credits are grants rather than permanent free capacity and partner-specific eligibility applies.",
        official_url="https://www.nvidia.com/en-us/startups/",
        notes="Future acquisition path if Thorio becomes eligible as a startup; not assumed to be available today.",
    ),
)


def get_source(source_id: str) -> FreeComputeSource:
    key = str(source_id).strip()
    for source in FREE_COMPUTE_SOURCES:
        if source.source_id == key:
            return source
    raise KeyError(f"unknown free compute source: {key}")


def immediately_eligible_individual_sources() -> tuple[FreeComputeSource, ...]:
    """Return zero-cost sources that do not require institutional/startup status."""
    return tuple(
        source
        for source in FREE_COMPUTE_SOURCES
        if source.zero_cost
        and source.eligibility is Eligibility.INDIVIDUAL
        and not source.requires_institution
        and not source.requires_startup_status
        and not source.requires_payment_method
    )


def physical_gpu_execution_sources() -> tuple[FreeComputeSource, ...]:
    """Return free sources capable of actual NVIDIA GPU execution."""
    return tuple(
        source
        for source in FREE_COMPUTE_SOURCES
        if source.zero_cost and source.gpu and source.cuda
    )


def direct_runner_candidates() -> tuple[FreeComputeSource, ...]:
    """Return sources that can technically host a persistent runner.

    Eligibility is intentionally not overridden. Callers must still satisfy the
    source's documented access requirements before acquisition.
    """
    return tuple(
        source
        for source in FREE_COMPUTE_SOURCES
        if source.zero_cost
        and source.persistent_runner
        and source.fabric_suitability is FabricSuitability.DIRECT_RUNNER
    )


def source_ids(sources: Iterable[FreeComputeSource]) -> tuple[str, ...]:
    return tuple(source.source_id for source in sources)
