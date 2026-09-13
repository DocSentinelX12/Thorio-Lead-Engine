#!/usr/bin/env python3
"""Send one explicit Gmail self-test through the already-authenticated Chrome CDP tab.

This script uses the live Gmail DOM only. It does not use passwords, cookies, screenshots,
synthetic selectors, or a separate login flow. The recipient is the configured Gmail account
itself. After Send, it inspects only visible DOM metadata/text needed to prove the send result.
"""
from __future__ import annotations

import base64
import json
import os
import re
import socket
import struct
import time
import urllib.request
from urllib.parse import urlsplit

CDP_HTTP = os.environ.get("THORIO_BROWSER_CDP_URL", "http://127.0.0.1:9222").rstrip("/")


def get_json(path: str):
    with urllib.request.urlopen(CDP_HTTP + path, timeout=10) as response:
        return json.load(response)


def ws_connect(url: str) -> socket.socket:
    parsed = urlsplit(url)
    if parsed.scheme != "ws":
        raise RuntimeError("Unsupported CDP websocket scheme")
    host = parsed.hostname or ""
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    sock = socket.create_connection((host, port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
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


def send_text(sock: socket.socket, text: str) -> None:
    payload = text.encode("utf-8")
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    length = len(masked)
    if length < 126:
        header = bytes((0x81, 0x80 | length))
    elif length < 65536:
        header = bytes((0x81, 0x80 | 126)) + struct.pack("!H", length)
    else:
        header = bytes((0x81, 0x80 | 127)) + struct.pack("!Q", length)
    sock.sendall(header + mask + masked)


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = []
    while size:
        chunk = sock.recv(size)
        if not chunk:
            raise RuntimeError("CDP websocket closed unexpectedly")
        chunks.append(chunk)
        size -= len(chunk)
    return b"".join(chunks)


def recv_text(sock: socket.socket) -> str:
    fragments = []
    while True:
        first, second = recv_exact(sock, 2)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", recv_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", recv_exact(sock, 8))[0]
        mask = recv_exact(sock, 4) if masked else b""
        payload = recv_exact(sock, length)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if opcode == 0x8:
            raise RuntimeError("CDP websocket closed")
        if opcode == 0x9:
            send_text(sock, payload.decode("utf-8"))
            continue
        if opcode in (0x1, 0x0):
            fragments.append(payload)
            if first & 0x80:
                return b"".join(fragments).decode("utf-8")


def cdp(sock: socket.socket, method: str, params=None, command_id: int = 1):
    send_text(sock, json.dumps({"id": command_id, "method": method, "params": params or {}}))
    deadline = time.time() + 15
    while time.time() < deadline:
        message = json.loads(recv_text(sock))
        if message.get("id") == command_id:
            if "error" in message:
                raise RuntimeError(f"CDP {method} failed: {message['error']}")
            return message.get("result", {})
    raise TimeoutError(f"Timed out waiting for {method}")


def evaluate(sock: socket.socket, expression: str, command_id: int):
    result = cdp(sock, "Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": True,
    }, command_id)
    value = result.get("result", {}).get("value")
    if value is None:
        exception = result.get("exceptionDetails")
        raise RuntimeError(f"Browser evaluation failed: {exception or result}")
    return value


def account_from_engine_env() -> str:
    path = os.path.expanduser("~/.thorio/engine.env")
    if not os.path.exists(path):
        raise RuntimeError(f"Missing {path}. The local Thorio environment must contain THORIO_ACCOUNT_GMAIL_USERNAME.")
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "THORIO_ACCOUNT_GMAIL_USERNAME":
            value = value.strip().strip('"').strip("'")
            if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
                return value
    raise RuntimeError("THORIO_ACCOUNT_GMAIL_USERNAME is not configured in ~/.thorio/engine.env.")


OPEN_COMPOSE_JS = r"""
(() => {
  const visible = el => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
  };
  const els = [...document.querySelectorAll('[role=button],button')].filter(visible);
  const el = els.find(e => /compose/i.test((e.getAttribute('aria-label') || '') + ' ' + (e.textContent || '')));
  if (!el) return {ok:false};
  el.click();
  return {ok:true};
})()
"""

FILL_AND_SEND_JS = r"""
(recipient) => {
  const visible = el => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
  };
  const by = (selector) => [...document.querySelectorAll(selector)].find(visible);
  const to = by('[aria-label="To recipients"]') || by('[role="combobox"][aria-label="To recipients"]');
  const subject = by('[name="subjectbox"]') || by('[aria-label="Subject"]');
  const body = by('[aria-label="Message Body"]') || by('[role="textbox"][aria-label="Message Body"]');
  const send = by('[role="button"][aria-label*="Send"]') || by('[aria-label*="Send"]');
  if (!to || !subject || !body || !send) {
    return {ok:false, missing:{to:!to,subject:!subject,body:!body,send:!send}};
  }
  to.focus();
  to.value = recipient;
  to.dispatchEvent(new Event('input',{bubbles:true}));
  to.dispatchEvent(new Event('change',{bubbles:true}));
  to.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));
  to.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));
  subject.focus();
  subject.value = 'Thorio Gmail self-test';
  subject.dispatchEvent(new Event('input',{bubbles:true}));
  subject.dispatchEvent(new Event('change',{bubbles:true}));
  body.focus();
  body.textContent = 'This is an authorized Thorio Gmail browser transport self-test.';
  body.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:null}));
  send.click();
  return {ok:true};
}
"""

CONFIRM_JS = r"""
(() => {
  const visible = el => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
  };
  const all = [...document.querySelectorAll('[role=alert],.vh,div,span')].filter(visible);
  const hits = all.filter(e => /message sent|sent to/i.test((e.textContent || '').trim())).slice(0,10);
  return hits.map(e => ({tag:e.tagName.toLowerCase(),role:e.getAttribute('role') || '',text:(e.textContent || '').trim().slice(0,160),aria:e.getAttribute('aria-label') || '',id:e.id || ''}));
})()
"""


def main() -> int:
    recipient = account_from_engine_env()
    pages = get_json("/json/list")
    gmail = [p for p in pages if str(p.get("url", "")).lower().startswith("https://mail.google.com/")]
    if not gmail:
        raise SystemExit("No live Gmail tab is open on the Thorio Chromium CDP session.")
    ws = str(gmail[0].get("webSocketDebuggerUrl", ""))
    if not ws:
        raise SystemExit("The Gmail tab has no CDP websocket endpoint.")
    sock = ws_connect(ws)
    try:
        opened = evaluate(sock, OPEN_COMPOSE_JS, 1)
        if not opened.get("ok"):
            raise SystemExit("Could not find the live Gmail Compose control.")
        time.sleep(1)
        sent = evaluate(sock, FILL_AND_SEND_JS, 2)
        if not sent.get("ok"):
            raise SystemExit(f"Could not complete the live Gmail composer: {sent.get('missing')}")
        deadline = time.time() + 8
        confirmation = []
        while time.time() < deadline:
            confirmation = evaluate(sock, CONFIRM_JS, 3)
            if confirmation:
                break
            time.sleep(0.25)
        print("=== THORIO GMAIL SELF-TEST ===")
        print("Recipient: [configured Gmail account, redacted]")
        print("Send action: LIVE Gmail composer")
        print("Confirmation:", json.dumps(confirmation, ensure_ascii=False))
        if not confirmation:
            print("RESULT: SEND ACTION COMPLETED, BUT NO POST-SEND DOM CONFIRMATION WAS OBSERVED.")
            return 2
        print("RESULT: LIVE GMAIL SEND CONFIRMED")
        return 0
    finally:
        sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
