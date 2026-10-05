from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTH_SCRIPT = ROOT / "infra" / "android-termux" / "authorize-browser.sh"
BOOTSTRAP_SCRIPT = ROOT / "infra" / "android-termux" / "bootstrap.sh"


def test_android_authorization_does_not_set_invalid_xkb_path():
    text = AUTH_SCRIPT.read_text(encoding="utf-8")
    assert "export XKB_CONFIG_ROOT" not in text
    assert "termux-x11 :1" in text
    assert "remote-debugging-port=9222" in text


def test_android_authorization_includes_gmail_as_outreach_only():
    text = AUTH_SCRIPT.read_text(encoding="utf-8")
    assert "7. Gmail (outreach only)" in text
    assert "Gmail is used only for authorized outbound outreach. It is not a collection source." in text
    assert "six collection accounts and Gmail" in text


def test_android_bootstrap_installs_browser_runtime_dependency():
    text = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
    assert "requirements-browser.txt" in text
    assert "THORIO_BROWSER_CDP_URL=http://127.0.0.1:9222" in text
    assert "THORIO_BROWSER_PROFILE_DIR=$PROFILE_DIR" in text


def test_android_bootstrap_uses_native_termux_playwright_installer():
    text = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
    assert "install-playwright-termux.py" in text
    assert "command -v pkg >/dev/null 2>&1" in text
    assert "requirements-browser.txt" in text
    assert "PLAYWRIGHT_BROWSERS_PATH=0" in text


def test_android_playwright_installer_is_pinned_and_verifies_official_wheel():
    installer = (ROOT / "infra" / "android-termux" / "install-playwright-termux.py").read_text(
        encoding="utf-8"
    )
    assert 'PLAYWRIGHT_VERSION = "1.58.0"' in installer
    assert "files.pythonhosted.org" in installer
    assert "sha256" in installer
    assert 'Object.defineProperty(process, "platform"' in installer
    assert "connect_over_cdp" in installer
