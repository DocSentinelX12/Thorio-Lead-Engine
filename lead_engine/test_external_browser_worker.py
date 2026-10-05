from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "infra" / "external-browser" / "browser-worker.py"
BOOTSTRAP = ROOT / "infra" / "external-browser" / "bootstrap.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "python-app.yml"


def test_external_browser_worker_is_headless_and_local_only():
    text = WORKER.read_text(encoding="utf-8")
    assert "chromium.launch" in text
    assert "new_context" in text
    assert "storage_state" in text
    assert "indexed_db=True" in text
    assert "launch_persistent_context" not in text
    assert "headless=True" in text
    assert "--remote-debugging-address=127.0.0.1" in text
    assert "THORIO_BROWSER_STORAGE_STATE_PATH" in text
    assert "Termux" not in text
    assert "termux" not in text


def test_production_workflow_wires_external_browser_state_persistence():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "THORIO_BROWSER_CDP_URL: \"http://127.0.0.1:9222\"" in text
    assert "THORIO_BROWSER_STORAGE_STATE_PATH: \"data/browser-state.json\"" in text
    assert "THORIO_BROWSER_STATE_ENCRYPTION_KEY" in text
    assert "thorio-browser-auth-state" in text
    assert "browser-worker.py" in text
    assert "browser-state.py decrypt" in text
    assert "browser-state.py encrypt" in text
    assert "actions/upload-artifact@v6" in text


def test_external_browser_state_adapter_is_encrypted():
    helper = (ROOT / "infra" / "external-browser" / "browser-state.py").read_text(encoding="utf-8")
    assert "Fernet" in helper
    assert "THORIO_BROWSER_STATE_ENCRYPTION_KEY" in helper
    assert "InvalidToken" in helper


def test_external_browser_bootstrap_uses_persistent_systemd_services():
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert "thorio-browser.service" in text
    assert "thorio-lead-engine.service" in text
    assert "Restart=always" in text
    assert "THORIO_BROWSER_CDP_URL=http://127.0.0.1:9222" in text
    assert "playwright install-deps chromium" in text
    assert "playwright install chromium --no-shell" in text


def test_rejected_runtime_paths_are_removed():
    assert not (ROOT / "infra" / "android-termux").exists()
    assert not (ROOT / "lead_engine" / "test_android_runtime_scripts.py").exists()
    assert not (ROOT / "infra" / "external-browser" / "lightning-supervisor.py").exists()
    assert not (ROOT / "infra" / "external-browser" / "lightning-start.sh").exists()
