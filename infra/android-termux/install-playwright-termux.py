#!/usr/bin/env python3
"""Install the pinned upstream Playwright Python wheel for native Termux.

Termux reports Android as the OS platform, while the upstream Playwright Python
wheel publishes Linux ARM64/x86_64 driver bundles. Pip therefore refuses the
wheel before installation. This installer verifies an official PyPI wheel,
installs it under an any-platform filename, and patches the bundled Node driver
to treat Android as Linux. The application continues to import the normal
`playwright` package and keeps its existing Playwright API unchanged.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


PLAYWRIGHT_VERSION = "1.58.0"

WHEELS = {
    "aarch64": {
        "filename": "playwright-1.58.0-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl",
        "url": "https://files.pythonhosted.org/packages/d9/a6/0e66ad04b6d3440dae73efb39540c5685c5fc95b17c8b29340b62abbd952/playwright-1.58.0-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl",
        "sha256": "8f9999948f1ab541d98812de25e3a8c410776aa516d948807140aff797b4bffa",
    },
    "x86_64": {
        "filename": "playwright-1.58.0-py3-none-manylinux1_x86_64.whl",
        "url": "https://files.pythonhosted.org/packages/f1/af/009958cbf23fac551a940d34e3206e6c7eed2b8c940d0c3afd1feb0b0589/playwright-1.58.0-py3-none-manylinux1_x86_64.whl",
        "sha256": "c95568ba1eda83812598c1dc9be60b4406dffd60b149bc1536180ad108723d6b",
    },
}

PATCH_PAYLOAD = (
    'Object.defineProperty(process, "platform", {value: "linux", configurable: true});\n'
    'Object.defineProperty(require("os"), "platform", {value: () => "linux", configurable: true});\n'
)


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _architecture() -> str:
    machine = os.uname().machine.lower()
    if machine in {"aarch64", "arm64"}:
        return "aarch64"
    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    raise RuntimeError(f"Unsupported Termux CPU architecture: {machine}")


def _download_and_verify(spec: dict[str, str], destination: Path) -> None:
    request = urllib.request.Request(
        spec["url"],
        headers={"User-Agent": "Thorio-Lead-Engine-Termux-Playwright"},
    )
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)

    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    if digest != spec["sha256"]:
        raise RuntimeError(
            f"Playwright wheel SHA-256 mismatch: expected {spec['sha256']}, got {digest}"
        )


def _playwright_dir() -> Path:
    spec = importlib.util.find_spec("playwright")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError("Playwright package could not be located after installation")
    return Path(next(iter(spec.submodule_search_locations)))


def _install_driver_package(package_dir: Path) -> Path:
    driver_dir = package_dir / "driver"
    package_root = driver_dir / "package"
    package_root.mkdir(parents=True, exist_ok=True)

    # Playwright 1.58.0's Python wheel is platform-tagged, but Termux cannot
    # consume its bundled Linux driver layout reliably. Use the official
    # platform-independent playwright-core package and the native Termux Node.js
    # runtime instead. This produces the exact driver layout expected by the
    # Python binding: driver/package/cli.js and driver/package/lib/coreBundle.js.
    with tempfile.TemporaryDirectory(prefix="thorio-playwright-core-") as temp:
        temp_dir = Path(temp)
        _run(
            [
                "npm",
                "pack",
                f"playwright-core@{PLAYWRIGHT_VERSION}",
                "--pack-destination",
                str(temp_dir),
            ]
        )
        archives = sorted(temp_dir.glob("playwright-core-*.tgz"))
        if len(archives) != 1:
            raise RuntimeError(
                f"Expected exactly one playwright-core archive, found {len(archives)}"
            )

        if package_root.exists():
            shutil.rmtree(package_root)
        package_root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archives[0], "r:gz") as archive:
            archive.extractall(driver_dir, filter="data")

    cli = package_root / "cli.js"
    if not cli.is_file():
        raise RuntimeError(f"Playwright driver cli.js was not found at {cli}")
    bundle = package_root / "lib" / "coreBundle.js"
    if not bundle.is_file():
        raise RuntimeError(f"Playwright coreBundle.js was not found at {bundle}")
    return bundle


def _patch_driver() -> Path:
    package_dir = _playwright_dir()
    bundle = _install_driver_package(package_dir)
    original = bundle.read_text(encoding="utf-8", errors="ignore")
    if 'Object.defineProperty(process, "platform"' in original:
        return bundle

    backup = bundle.with_suffix(bundle.suffix + ".thorio-backup")
    if not backup.exists():
        shutil.copy2(bundle, backup)

    temporary = bundle.with_suffix(bundle.suffix + ".thorio-tmp")
    temporary.write_text(PATCH_PAYLOAD + original, encoding="utf-8")
    os.replace(temporary, bundle)

    patched = bundle.read_text(encoding="utf-8", errors="ignore")
    if 'Object.defineProperty(process, "platform"' not in patched:
        raise RuntimeError("Playwright Android compatibility patch could not be verified")
    return bundle


def install() -> None:
    if not os.environ.get("PREFIX"):
        raise RuntimeError("This installer is intended for Termux only")

    architecture = _architecture()
    spec = WHEELS[architecture]

    _run(["pkg", "install", "-y", "python-greenlet", "nodejs", "procps", "termux-api"])
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "pyee>=13,<14",
            "typing-extensions>=4.12",
        ]
    )

    with tempfile.TemporaryDirectory(prefix="thorio-playwright-") as temp:
        temp_dir = Path(temp)
        downloaded = temp_dir / spec["filename"]
        _download_and_verify(spec, downloaded)

        # Pip validates the platform tag encoded in the filename. The wheel
        # contains pure Python plus its bundled Node driver, so only the Python
        # package tag is relevant after the Termux platform has been verified.
        injected = temp_dir / f"playwright-{PLAYWRIGHT_VERSION}-py3-none-any.whl"
        shutil.copy2(downloaded, injected)
        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--no-deps",
                "--no-cache-dir",
                str(injected),
            ]
        )

    bundle = _patch_driver()

    import playwright  # noqa: PLC0415
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    if getattr(playwright, "__version__", "") != PLAYWRIGHT_VERSION:
        raise RuntimeError(
            f"Unexpected Playwright version after installation: {getattr(playwright, '__version__', 'unknown')}"
        )

    with sync_playwright() as playwright_runtime:
        if not hasattr(playwright_runtime.chromium, "connect_over_cdp"):
            raise RuntimeError("Installed Playwright does not expose Chromium CDP support")

    print(f"Installed Playwright {PLAYWRIGHT_VERSION} for Termux {architecture}.")
    print(f"Verified driver package and Android compatibility patch: {bundle}")


if __name__ == "__main__":
    install()
