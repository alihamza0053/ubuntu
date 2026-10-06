"""
Ollama model management for the Apps section (Models tab).

The panel talks to Ollama on 127.0.0.1:<port> — the same box, never through
the public domain, so no API key is involved here. Standard library only
(urllib), like the rest of the backend's outbound calls.

Pulls are multi-GB downloads, so they run in a background thread and their
progress is kept in memory for the page to poll; closing the browser tab does
not cancel a pull. One pull at a time.
"""
import json
import re
import threading
import time
import urllib.error
import urllib.request

from fastapi import HTTPException

# "llama3.2:3b", "qwen2.5-coder:7b", "hf.co/user/repo:Q4_K_M", "user/model"
MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/:]{0,199}$")

_pull = {"model": None, "running": False, "status": "", "completed": 0, "total": 0,
         "error": None, "started": None, "finished": None}
_pull_lock = threading.Lock()


def validate_model(name: str) -> str:
    name = (name or "").strip()
    if not MODEL_NAME_RE.match(name) or ".." in name:
        raise HTTPException(status_code=400,
                            detail="Model name looks wrong — e.g. llama3.2:3b or qwen2.5:7b")
    return name


def _url(port: int, path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


def _request(port: int, method: str, path: str, body: dict | None = None,
             timeout: float = 30):
    """One JSON request to Ollama; raises a readable HTTPException on failure."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(_url(port, path), data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="ignore")
        try:
            detail = json.loads(detail).get("error", detail)
        except ValueError:
            pass
        raise HTTPException(status_code=exc.code if exc.code < 500 else 502,
                            detail=f"Ollama: {detail or exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama isn't answering — start it on the Overview tab "
                   f"({getattr(exc, 'reason', exc)})") from exc
    return json.loads(raw) if raw else {}


def version(port: int) -> str | None:
    try:
        return _request(port, "GET", "/api/version", timeout=3).get("version")
    except HTTPException:
        return None


def list_models(port: int) -> list[dict]:
    """Installed models, newest first: name, size (bytes), modified, details."""
    tags = _request(port, "GET", "/api/tags", timeout=10).get("models", [])
    try:
        loaded = {m.get("name") for m in _request(port, "GET", "/api/ps", timeout=5)
                  .get("models", [])}
    except HTTPException:
        loaded = set()
    out = []
    for m in tags:
        details = m.get("details") or {}
        out.append({
            "name": m.get("name"),
            "size": m.get("size", 0),
            "modified": m.get("modified_at"),
            "family": details.get("family"),
            "parameters": details.get("parameter_size"),
            "quantization": details.get("quantization_level"),
            "loaded": m.get("name") in loaded,
        })
    return out


def delete_model(port: int, name: str) -> None:
    _request(port, "DELETE", "/api/delete", {"model": validate_model(name)})


def generate(port: int, model: str, prompt: str) -> dict:
    """One non-streamed answer, for the Models tab's quick test."""
    started = time.time()
    res = _request(port, "POST", "/api/generate",
                   {"model": validate_model(model), "prompt": prompt, "stream": False},
                   timeout=600)
    tokens = res.get("eval_count") or 0
    gen_seconds = (res.get("eval_duration") or 0) / 1e9
    return {
        "response": res.get("response", ""),
        "seconds": round(time.time() - started, 1),
        "tokens": tokens,
        "tokens_per_second": round(tokens / gen_seconds, 1) if gen_seconds else None,
    }


# ---------------------------------------------------------------------------
# Pull (background)
# ---------------------------------------------------------------------------

def pull_status() -> dict:
    with _pull_lock:
        return dict(_pull)


def _pull_worker(port: int, model: str) -> None:
    req = urllib.request.Request(
        _url(port, "/api/pull"), method="POST",
        data=json.dumps({"model": model, "stream": True}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        # Ollama streams one JSON object per line: {"status": "...",
        # "digest": "...", "total": N, "completed": M} … {"status": "success"}
        with urllib.request.urlopen(req, timeout=60 * 60 * 6) as resp:
            for line in resp:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                with _pull_lock:
                    if msg.get("error"):
                        _pull["error"] = msg["error"]
                        break
                    _pull["status"] = msg.get("status", _pull["status"])
                    if msg.get("total"):
                        _pull["total"] = msg["total"]
                        _pull["completed"] = msg.get("completed", 0)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode(errors="ignore")
        try:
            text = json.loads(text).get("error", text)
        except ValueError:
            pass
        with _pull_lock:
            _pull["error"] = text or str(exc)
    except Exception as exc:  # noqa: BLE001 — report whatever went wrong
        with _pull_lock:
            _pull["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        with _pull_lock:
            if not _pull["error"] and _pull["status"] != "success":
                _pull["error"] = f"pull ended early (last status: {_pull['status'] or 'none'})"
            _pull["running"] = False
            _pull["finished"] = time.time()


def start_pull(port: int, model: str) -> None:
    model = validate_model(model)
    _request(port, "GET", "/api/version", timeout=3)    # 503 "not answering" if it's down
    with _pull_lock:
        if _pull["running"]:
            raise HTTPException(status_code=409,
                                detail=f"Already pulling {_pull['model']} — wait for it to finish")
        _pull.update(model=model, running=True, status="starting", completed=0,
                     total=0, error=None, started=time.time(), finished=None)
    threading.Thread(target=_pull_worker, args=(port, model), daemon=True).start()
