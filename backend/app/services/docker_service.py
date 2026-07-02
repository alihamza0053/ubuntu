"""
Docker management: list/control containers, images and volumes for the whole
host (not just panel-managed apps). Uses the docker CLI (`--format {{json .}}`)
through the restricted sudo rule.
"""
import json
import subprocess

from fastapi import HTTPException

DOCKER = ["sudo", "-n", "docker"]


def _run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([*DOCKER, *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Docker is not installed")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="docker command timed out")


def ready() -> bool:
    try:
        r = _run(["version", "--format", "{{.Server.Version}}"], timeout=15)
        return r.returncode == 0
    except HTTPException:
        return False


def _json_lines(out: str) -> list[dict]:
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def list_containers() -> list[dict]:
    r = _run(["ps", "-a", "--format", "{{json .}}"])
    items = []
    for d in _json_lines(r.stdout):
        items.append({
            "id": d.get("ID", ""),
            "name": d.get("Names", ""),
            "image": d.get("Image", ""),
            "state": d.get("State", ""),      # running / exited / created / paused
            "status": d.get("Status", ""),    # human-readable uptime
            "ports": d.get("Ports", ""),
            "managed": d.get("Names", "").startswith("app_"),  # panel-installed app
        })
    return items


def list_images() -> list[dict]:
    r = _run(["images", "--format", "{{json .}}"])
    items = []
    for d in _json_lines(r.stdout):
        repo, tag = d.get("Repository", "<none>"), d.get("Tag", "")
        items.append({
            "id": d.get("ID", ""),
            "name": f"{repo}:{tag}" if tag else repo,
            "size": d.get("Size", ""),
            "created": d.get("CreatedSince", ""),
        })
    return items


def list_volumes() -> list[dict]:
    r = _run(["volume", "ls", "--format", "{{json .}}"])
    return [{"name": d.get("Name", ""), "driver": d.get("Driver", "")}
            for d in _json_lines(r.stdout)]


def container_action(cid: str, action: str) -> str:
    if action not in ("start", "stop", "restart", "remove"):
        raise HTTPException(status_code=400, detail="invalid action")
    args = ["rm", "-f", cid] if action == "remove" else [action, cid]
    r = _run(args, timeout=120)
    if r.returncode != 0:
        raise HTTPException(status_code=500, detail=(r.stderr or r.stdout)[:300])
    return r.stdout.strip() or f"{action} ok"


def remove_image(image_id: str) -> str:
    r = _run(["rmi", "-f", image_id], timeout=120)
    if r.returncode != 0:
        raise HTTPException(status_code=500, detail=(r.stderr or r.stdout)[:300])
    return r.stdout.strip() or "image removed"


def remove_volume(name: str) -> str:
    r = _run(["volume", "rm", name], timeout=60)
    if r.returncode != 0:
        raise HTTPException(status_code=500, detail=(r.stderr or r.stdout)[:300])
    return "volume removed"


def prune() -> str:
    r = _run(["system", "prune", "-f"], timeout=180)
    return (r.stdout or r.stderr).strip()[-2000:]


def logs_cmd(cid: str) -> list[str]:
    return [*DOCKER, "logs", "-f", "--tail", "200", cid]


def stats() -> dict:
    return {
        "ready": True,
        "containers": list_containers(),
        "images": list_images(),
        "volumes": list_volumes(),
    }
