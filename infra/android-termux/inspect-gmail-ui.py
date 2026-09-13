#!/usr/bin/env python3
"""Inspect the live Gmail UI through Chromium CDP without screenshots or message contents."""
from __future__ import annotations

import base64
import json
import os
import re
import socket
import struct
import time
import urllib.request
from pathlib import Path
from typing import Any

CDP_HTTP = os.environ.get("THORIO_BROWSER_CDP_URL", "http://127.0.0.1:9222").rstrip("/")
REPORT = Path(os.environ.get("THORIO_GMAIL_UI_REPORT", "~/.thorio/logs/gmail-ui-diagnostic.json")).expanduser()


def _get_json(path: str) -> Any:
    with urllib.request.urlopen(CDP_HTTP + path, timeout=10) as response:
        return json.load(response)


def _websocket_connect(url: str) -> socket.socket:
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    if parsed.scheme != "ws":
        raise RuntimeError(f"unsupported CDP websocket scheme: {parsed.scheme}")
    host = parsed.hostname or ""
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    sock = socket.create_connection((host, port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).encode("ascii")
    sock.sendall(request)
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("CDP websocket closed during handshake")
        response += chunk
    if not response.startswith(b"HTTP/1.1 101"):
        raise RuntimeError("CDP websocket handshake failed")
    return sock


def _send_text(sock: socket.socket, text: str) -> None:
    payload = text.encode("utf-8")
    mask_key = os.urandom(4)
    masked = bytes(byte ^ mask_key[i % 4] for i, byte in enumerate(payload))
    length = len(masked)
    if length < 126:
        header = bytes((0x81, 0x80 | length))
    elif length < 65536:
        header = bytes((0x81, 0x80 | 126)) + struct.pack("!H", length)
    else:
        header = bytes((0x81, 0x80 | 127)) + struct.pack("!Q", length)
    sock.sendall(header + mask_key + masked)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeError("CDP websocket closed unexpectedly")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_text(sock: socket.socket) -> str:
    fragments: list[bytes] = []
    while True:
        first, second = _recv_exact(sock, 2)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", _recv_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", _recv_exact(sock, 8))[0]
        mask_key = _recv_exact(sock, 4) if masked else b""
        payload = _recv_exact(sock, length)
        if masked:
            payload = bytes(byte ^ mask_key[i % 4] for i, byte in enumerate(payload))
        if opcode == 0x8:
            raise RuntimeError("CDP websocket closed")
        if opcode == 0x9:
            continue
        if opcode in (0x1, 0x0):
            fragments.append(payload)
            if first & 0x80:
                return b"".join(fragments).decode("utf-8")


def _cdp(sock: socket.socket, method: str, params: dict[str, Any] | None = None, command_id: int = 1) -> dict[str, Any]:
    _send_text(sock, json.dumps({"id": command_id, "method": method, "params": params or {}}))
    deadline = time.time() + 15
    while time.time() < deadline:
        message = json.loads(_recv_text(sock))
        if message.get("id") == command_id:
            if "error" in message:
                raise RuntimeError(f"CDP {method} failed: {message['error']}")
            return message.get("result", {})
    raise TimeoutError(f"timed out waiting for CDP {method}")


INSPECT_JS = r"""
(() => {
  const clean = value => value ? String(value).replace(/\s+/g, " ").trim().slice(0, 240) : "";
  const visible = el => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  };
  const attrs = el => ({
    tag: el.tagName.toLowerCase(),
    type: clean(el.getAttribute("type")),
    role: clean(el.getAttribute("role")),
    aria_label: clean(el.getAttribute("aria-label")),
    aria_labelledby: clean(el.getAttribute("aria-labelledby")),
    aria_describedby: clean(el.getAttribute("aria-describedby")),
    name: clean(el.getAttribute("name")),
    placeholder: clean(el.getAttribute("placeholder")),
    title: clean(el.getAttribute("title")),
    id: clean(el.id),
    class_prefix: clean(el.className).slice(0, 240),
    data_testid: clean(el.getAttribute("data-testid")),
    contenteditable: el.getAttribute("contenteditable") === "true",
    visible: visible(el)
  });
  const all = Array.from(document.querySelectorAll("input, textarea, [contenteditable=\"true\"], button, [role=button], [role=combobox], [role=textbox]"));
  const elements = all.filter(visible).map(attrs);
  const keywords = /compose|send|recipient|subject|message|body|to|sent|delivered|message sent|saved/i;
  const relevant = elements.filter(item => Object.values(item).some(value => typeof value === "string" && keywords.test(value)));

  const textNodes = Array.from(document.querySelectorAll("body *"))
    .filter(visible)
    .map(el => clean(el.innerText || el.textContent || ""))
    .filter(text => text && /sent|delivered|message sent|saved|recipient|compose|send/i.test(text) && text.length <= 240)
    .slice(-80);

  return {
    page: { origin: location.origin, path: location.pathname, title: document.title },
    counts: { visible_interactive: elements.length, relevant: relevant.length, status_text_candidates: textNodes.length },
    relevant,
    status_text_candidates: [...new Set(textNodes)]
  };
})()
"""


def _redact(value: str) -> str:
    return re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[email-redacted]", value)


def _selector_candidates(item: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    if item.get("id"):
        candidates.append(f"#{item['id']}")
    if item.get("data_testid"):
        candidates.append(f"[data-testid={json.dumps(item['data_testid'])}]")
    if item.get("aria_label"):
        candidates.append(f"[aria-label={json.dumps(item['aria_label'])}]")
    if item.get("name"):
        candidates.append(f"[name={json.dumps(item['name'])}]")
    if item.get("placeholder"):
        candidates.append(f"[placeholder={json.dumps(item['placeholder'])}]")
    if item.get("role") and item.get("aria_label"):
        candidates.append(f"[role={json.dumps(item['role'])}][aria-label={json.dumps(item['aria_label'])}]")
    return candidates[:4]


def _print_compact_report(value: dict[str, Any]) -> None:
    page = value.get("page", {})
    counts = value.get("counts", {})
    print("\n=== THORIO LIVE GMAIL UI REPORT ===")
    print(f"URL: {_redact(str(page.get('origin', '')) + str(page.get('path', '')))}")
    print(f"TITLE: {_redact(str(page.get('title', '')))}")
    print(f"VISIBLE_INTERACTIVE: {counts.get('visible_interactive', 0)}")
    print(f"RELEVANT: {counts.get('relevant', 0)}")
    print(f"STATUS_TEXT_CANDIDATES: {counts.get('status_text_candidates', 0)}")
    print("CONTROLS:")
    for index, item in enumerate(value.get("relevant", []), 1):
        summary = {key: _redact(str(item.get(key, ""))) for key in ("tag", "type", "role", "aria_label", "name", "placeholder", "title", "id", "data_testid", "contenteditable") if item.get(key, "") not in ("", False)}
        print(f"{index}. {json.dumps(summary, ensure_ascii=False, separators=(',', ':'))}")
        selectors = _selector_candidates(item)
        if selectors:
            print(f"   SELECTORS: {' | '.join(_redact(s) for s in selectors)}")
    if value.get("status_text_candidates"):
        print("STATUS_TEXT:")
        for text in value["status_text_candidates"]:
            print(f"- {_redact(text)}")
    print("=== END REPORT ===\n")


def main() -> int:
    pages = _get_json("/json/list")
    gmail_pages = [p for p in pages if str(p.get("url", "")).lower().startswith("https://mail.google.com/")]
    if not gmail_pages:
        raise SystemExit("No live Gmail tab is open in the Chromium instance on 127.0.0.1:9222.")
    page = gmail_pages[0]
    websocket_url = str(page.get("webSocketDebuggerUrl", "")).strip()
    if not websocket_url:
        raise SystemExit("The live Gmail tab did not expose a CDP websocket endpoint.")
    sock = _websocket_connect(websocket_url)
    try:
        result = _cdp(sock, "Runtime.evaluate", {"expression": INSPECT_JS, "returnByValue": True, "awaitPromise": True})
    finally:
        sock.close()
    value = result.get("result", {}).get("value")
    if not isinstance(value, dict):
        raise SystemExit("Gmail DOM inspection returned no structured result.")
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cdp_endpoint": CDP_HTTP,
        "tab_type": page.get("type"),
        "gmail_url": "https://mail.google.com/",
        "inspection": value,
        "privacy": {"message_contents_read": False, "input_values_read": False, "cookies_read": False, "local_storage_read": False, "passwords_read": False, "screenshots_taken": False},
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Gmail UI diagnostic written to {REPORT}")
    _print_compact_report(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
