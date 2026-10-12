import os
import subprocess
import sys


def test_standalone_coordinator_skips_application_patch_stack():
    env = os.environ.copy()
    env["THORIO_COMPUTE_COORDINATOR_STANDALONE"] = "1"
    script = """
import sys
import lead_engine
import lead_engine.compute_coordinator
unexpected = {
    "lead_engine.html_fallback",
    "lead_engine.source_overrides",
    "lead_engine.source_specific_collectors",
    "lead_engine.research_integrity",
    "lead_engine.production_throughput_override",
}
loaded = unexpected.intersection(sys.modules)
assert not loaded, f"application patch stack loaded in standalone mode: {sorted(loaded)}"
for name in (
    "lead_engine.zerogpu_execution",
    "lead_engine.openhydra_execution",
    "lead_engine.joule_execution",
    "lead_engine.bothy_execution",
    "lead_engine.swarmllm_execution",
    "lead_engine.viiwork_execution",
    "lead_engine.moregpu_execution",
):
    assert name not in sys.modules, f"disabled optional provider imported: {name}"
"""
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
