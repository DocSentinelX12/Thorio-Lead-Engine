from lead_engine.free_compute_source_catalog import (
    Eligibility,
    FabricSuitability,
    direct_runner_candidates,
    get_source,
    immediately_eligible_individual_sources,
    physical_gpu_execution_sources,
    source_ids,
)


def test_individual_zero_cost_gpu_sources_require_no_payment_method():
    sources = immediately_eligible_individual_sources()
    ids = source_ids(sources)
    assert "paperspace_gradient_free_gpu" in ids
    assert "kaggle_notebooks_gpu" in ids
    assert "huggingface_zerogpu" in ids
    assert "google_colab_free" in ids
    assert all(source.zero_cost for source in sources)
    assert all(source.eligibility is Eligibility.INDIVIDUAL for source in sources)
    assert all(not source.requires_payment_method for source in sources)


def test_physical_gpu_source_catalog_never_confuses_gpu_access_with_persistent_runner():
    sources = physical_gpu_execution_sources()
    assert sources
    assert all(source.zero_cost and source.gpu and source.cuda for source in sources)
    assert get_source("kaggle_notebooks_gpu").persistent_runner is False
    assert get_source("huggingface_zerogpu").fabric_suitability is FabricSuitability.EPHEMERAL_EXECUTION


def test_direct_runner_candidates_preserve_eligibility_boundaries():
    sources = direct_runner_candidates()
    ids = source_ids(sources)
    assert "access_jetstream2" in ids
    assert "national_research_platform" in ids
    assert "nvidia_inception_partner_credits" in ids
    assert all(source.zero_cost for source in sources)
    assert get_source("access_jetstream2").requires_institution is True
    assert get_source("national_research_platform").requires_institution is True
    assert get_source("nvidia_inception_partner_credits").eligibility is Eligibility.STARTUP_REQUIRED


def test_modal_is_catalogued_but_blocked_by_no_payment_method_rule():
    modal = get_source("modal_starter_free_compute")
    assert modal.zero_cost is True
    assert modal.requires_payment_method is True
    assert modal.fabric_suitability is FabricSuitability.EPHEMERAL_EXECUTION


def test_unknown_source_fails_closed():
    try:
        get_source("does-not-exist")
    except KeyError:
        return
    raise AssertionError("unknown compute source must fail closed")
