from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "infra" / "external-browser" / "browser-worker.py"
BOOTSTRAP = ROOT / "infra" / "external-browser" / "bootstrap.sh"


def test_external_browser_worker_is_headless_and_local_only():
    text = WORKER.read_text(encoding="utf-8")
    assert "launch_persistent_context" in text
    assert "headless=True" in text
    assert "--remote-debugging-address=127.0.0.1" in text
    assert "THORIO_BROWSER_PROFILE_DIR" in text
    assert "Termux" not in text
    assert "termux" not in text


def test_external_browser_bootstrap_uses_persistent_systemd_services():
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert "thorio-browser.service" in text
    assert "thorio-lead-engine.service" in text
    assert "Restart=always" in text
    assert "THORIO_BROWSER_CDP_URL=http://127.0.0.1:9222" in text
    assert "playwright install-deps chromium" in text
    assert "playwright install chromium --no-shell" in text
    assert "Termux" not in text
    assert "termux" not in text


def test_android_browser_runtime_path_is_removed():
    assert not (ROOT / "infra" / "android-termux").exists()
    assert not (ROOT / "lead_engine" / "test_android_runtime_scripts.py").exists()


def test_lightning_runtime_is_no_card_and_persistent():
    start = (ROOT / "infra" / "external-browser" / "lightning-start.sh").read_text(encoding="utf-8")
    supervisor = (ROOT / "infra" / "external-browser" / "lightning-supervisor.py").read_text(encoding="utf-8")
    assert "browser-profile" in start
    assert "lightning-supervisor.py" in start
    assert "launch_persistent_context" in (ROOT / "infra" / "external-browser" / "browser-worker.py").read_text(encoding="utf-8")
    assert "Restart" not in start
    assert "Termux" not in start
    assert "Termux" not in supervisor
    assert 'line.startswith("export ")' in supervisor
