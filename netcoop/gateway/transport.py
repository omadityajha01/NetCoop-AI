"""HTTP transport for the A2A gateway (stdlib only), plus record/replay for `netcoop replay`."""

from __future__ import annotations

import base64
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol


class TransportError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class Transport(Protocol):
    def get(self, url: str, timeout: float, max_bytes: int, key: str) -> bytes: ...

    def post(self, url: str, body: bytes, timeout: float, max_bytes: int, key: str) -> bytes: ...


def _read_capped(resp, max_bytes: int) -> bytes:
    data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise TransportError("TOO_LARGE", f"response exceeds {max_bytes} bytes")
    return data


class HttpTransport:
    def _do(self, req: urllib.request.Request, timeout: float, max_bytes: int) -> bytes:
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URL comes from allowlist only
                return _read_capped(resp, max_bytes)
        except TransportError:
            raise
        except urllib.error.HTTPError as exc:
            raise TransportError("HTTP", f"HTTP {exc.code}") from exc
        except TimeoutError as exc:
            raise TransportError("TIMEOUT", f"no response within {timeout:g}s") from exc
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            if "timed out" in str(reason):
                raise TransportError("TIMEOUT", f"no response within {timeout:g}s") from exc
            raise TransportError("UNREACHABLE", str(reason)[:120]) from exc

    def get(self, url: str, timeout: float, max_bytes: int, key: str) -> bytes:
        return self._do(urllib.request.Request(url, method="GET", headers={"Accept": "application/json"}), timeout, max_bytes)

    def post(self, url: str, body: bytes, timeout: float, max_bytes: int, key: str) -> bytes:
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        return self._do(req, timeout, max_bytes)


class RecordingTransport:
    """Wraps a transport and records every exchange to runs/<id>/external.jsonl (for byte-identical replay)."""

    def __init__(self, inner: Transport, path: Path, *, append: bool = False):
        self.inner = inner
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not append:  # `netcoop resume` appends to an interrupted run's recording instead of truncating it
            path.write_text("", encoding="utf-8")

    def _record(self, kind: str, url: str, key: str, data: bytes | None, err: TransportError | None) -> None:
        line = {"kind": kind, "url": url, "key": key,
                "body_b64": base64.b64encode(data).decode() if data is not None else None,
                "error": [err.code, err.detail] if err else None}
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, sort_keys=True) + "\n")

    def get(self, url: str, timeout: float, max_bytes: int, key: str) -> bytes:
        try:
            data = self.inner.get(url, timeout, max_bytes, key)
        except TransportError as e:
            self._record("get", url, key, None, e)
            raise
        self._record("get", url, key, data, None)
        return data

    def post(self, url: str, body: bytes, timeout: float, max_bytes: int, key: str) -> bytes:
        try:
            data = self.inner.post(url, body, timeout, max_bytes, key)
        except TransportError as e:
            self._record("post", url, key, None, e)
            raise
        self._record("post", url, key, data, None)
        return data


class ReplayTransport:
    """Serves recorded responses keyed by (kind, url, key). Unknown exchanges look unreachable."""

    def __init__(self, path: Path | None):
        self._rec: dict[tuple[str, str, str], list[dict]] = {}
        if path is not None and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    self._rec.setdefault((r["kind"], r["url"], r["key"]), []).append(r)

    def _serve(self, kind: str, url: str, key: str) -> bytes:
        lst = self._rec.get((kind, url, key))
        if not lst:
            raise TransportError("UNREACHABLE", "not in recording")
        r = lst.pop(0) if len(lst) > 1 else lst[0]
        if r["error"]:
            raise TransportError(r["error"][0], r["error"][1])
        return base64.b64decode(r["body_b64"])

    def get(self, url: str, timeout: float, max_bytes: int, key: str) -> bytes:
        return self._serve("get", url, key)

    def post(self, url: str, body: bytes, timeout: float, max_bytes: int, key: str) -> bytes:
        return self._serve("post", url, key)
