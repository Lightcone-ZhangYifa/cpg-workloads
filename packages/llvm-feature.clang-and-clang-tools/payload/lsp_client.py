"""Small dependency-free, bounded stdio LSP client used by the clangd check."""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


class LSPClient:
    def __init__(self, argv: list[str], cwd: Path, log_dir: Path, env: dict[str, str]):
        self.argv = argv
        self._stderr = (log_dir / "clangd.stderr.log").open("wb")
        self._wire = (log_dir / "lsp-messages.jsonl").open("w", encoding="utf-8")
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue()
        self._responses: dict[int, Any] = {}
        self.notifications: list[dict[str, Any]] = []
        self._next_id = 1
        self.process = subprocess.Popen(argv, cwd=cwd, env=env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self._stderr)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _record(self, direction: str, payload: Any) -> None:
        with self._lock:
            self._wire.write(json.dumps({"direction": direction, "message": payload},
                                        ensure_ascii=False) + "\n")
            self._wire.flush()

    def _read(self) -> None:
        try:
            while True:
                headers = {}
                while True:
                    line = self.process.stdout.readline()
                    if not line:
                        raise EOFError("clangd stdout closed")
                    if line in (b"\r\n", b"\n"):
                        break
                    key, value = line.decode("ascii").split(":", 1)
                    headers[key.lower()] = value.strip()
                size = int(headers["content-length"])
                if not 0 <= size <= 16 * 1024 * 1024:
                    raise ValueError("LSP message exceeds allowed size")
                body = b""
                while len(body) < size:
                    chunk = self.process.stdout.read(size - len(body))
                    if not chunk:
                        raise EOFError("truncated LSP body")
                    body += chunk
                payload = json.loads(body.decode("utf-8"))
                self._record("receive", payload)
                self._queue.put(payload)
        except Exception as exc:
            self._queue.put(exc)

    def send(self, method: str, params: Any, request: bool = False) -> int | None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        request_id = None
        if request:
            request_id = self._next_id
            self._next_id += 1
            payload["id"] = request_id
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._record("send", payload)
        self.process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
        self.process.stdin.write(body)
        self.process.stdin.flush()
        return request_id

    def _pump(self, timeout: float) -> None:
        try:
            payload = self._queue.get(timeout=max(timeout, 0.001))
        except queue.Empty as exc:
            raise TimeoutError("No LSP message before the request deadline") from exc
        if isinstance(payload, Exception):
            raise payload
        if "id" in payload and "method" not in payload:
            self._responses[payload["id"]] = payload
        else:
            self.notifications.append(payload)
            # The test does not advertise dynamic registration or configuration.
            # Reply to harmless server requests instead of hanging the process.
            if "id" in payload:
                response = {"jsonrpc": "2.0", "id": payload["id"], "result": None}
                body = json.dumps(response).encode()
                self._record("send", response)
                self.process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
                self.process.stdin.flush()

    def request(self, method: str, params: Any, timeout: float = 30) -> Any:
        request_id = self.send(method, params, request=True)
        end = time.monotonic() + timeout
        while request_id not in self._responses:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"LSP request timed out: {method}")
            self._pump(remaining)
        response = self._responses.pop(request_id)
        if "error" in response:
            raise RuntimeError(f"{method}: {response['error']}")
        return response.get("result")

    def diagnostics(self, uri: str, version: int, timeout: float = 30) -> list[dict]:
        end = time.monotonic() + timeout
        while True:
            for note in reversed(self.notifications):
                params = note.get("params", {})
                if (note.get("method") == "textDocument/publishDiagnostics" and
                        params.get("uri") == uri and params.get("version") == version):
                    return params.get("diagnostics", [])
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"No diagnostics for {uri} version {version}")
            self._pump(remaining)

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.request("shutdown", None, timeout=5)
                self.send("exit", None)
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
                self.process.wait(timeout=5)
        self._reader.join(timeout=2)
        self._stderr.close()
        self._wire.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def position_of(text: str, token: str, occurrence: int = 0) -> dict[str, int]:
    offset = -1
    for _ in range(occurrence + 1):
        offset = text.index(token, offset + 1)
    before = text[:offset]
    # All checked fixtures are ASCII. This is the UTF-16 character offset too.
    return {"line": before.count("\n"), "character": len(before.rsplit("\n", 1)[-1])}
