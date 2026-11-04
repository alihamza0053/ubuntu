"""
Bulk controls (Projects page, administrators only).

  * Pipelines & scheduled scripts — pause all (remembering which were on, and
    stopping pipelines that are running right now), resume only those or all.
  * Dashboards — stop all running ones (remembering which), start again only
    those or every project that has a dashboard.

What was paused/stopped is kept in the settings table, so "only the previous
ones" still works after a panel restart. Each project is handled on its own:
one failing dashboard never stops the rest, and the result lists every one.
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..deps import require_admin
from ..models import PipelineSchedule, Project, Schedule, Setting
from ..services import bg_tasks, pipeline_service, scheduler_service, supervisor_service
from ..services.activity import log_activity
from .dashboard import start_dashboard
from .projects import project_root

router = APIRouter(prefix="/api/bulk", tags=["bulk"], dependencies=[Depends(require_admin)])

PAUSED_KEY = "bulk_paused_schedules"        # {"pipelines": [ids], "schedules": [ids], "at": iso}
STOPPED_KEY = "bulk_stopped_dashboards"     # {"projects": [names], "at": iso}
TASK = "bulk-dashboards"


def _get(db: Session, key: str) -> dict | None:
    row = db.query(Setting).filter(Setting.key == key).first()
    try:
        return json.loads(row.value) if row and row.value else None
    except ValueError:
        return None


def _put(db: Session, key: str, value: dict | None) -> None:
    row = db.query(Setting).filter(Setting.key == key).first()
    text = json.dumps(value) if value else ""
    if row is None:
        db.add(Setting(key=key, value=text))
    else:
        row.value = text
    db.commit()


def _has_dashboard(project: Project) -> bool:
    return (project_root(project) / "dashboard" / "app.py").is_file()


@router.get("/status")
def status(db: Session = Depends(get_db)):
    projects = db.query(Project).all()
    statuses = supervisor_service.all_statuses()
    running = [p.name for p in projects
               if supervisor_service.state_from_raw(statuses.get(supervisor_service.program_name(p.name), ""))
               == "RUNNING"]
    pipes = db.query(PipelineSchedule).all()
    scheds = db.query(Schedule).all()
    paused, stopped = _get(db, PAUSED_KEY), _get(db, STOPPED_KEY)
    return {
        "pipelines": {"total": len(pipes), "active": sum(1 for p in pipes if p.is_active),
                      "running_now": sum(1 for p in projects if pipeline_service.is_pipeline_running(p.id))},
        "schedules": {"total": len(scheds), "active": sum(1 for s in scheds if s.is_active)},
        "paused": paused and {"pipelines": len(paused.get("pipelines", [])),
                              "schedules": len(paused.get("schedules", [])), "at": paused.get("at")},
        "dashboards": {"total": sum(1 for p in projects if _has_dashboard(p)), "running": len(running)},
        "stopped": stopped and {"projects": stopped.get("projects", []), "at": stopped.get("at")},
        "task": bg_tasks.state(TASK),
    }


# ---------------------------------------------------------------------------
# pipelines + scheduled scripts
# ---------------------------------------------------------------------------
@router.post("/pipelines/pause")
def pause_pipelines(db: Session = Depends(get_db)):
    pipes = db.query(PipelineSchedule).filter(PipelineSchedule.is_active.is_(True)).all()
    scheds = db.query(Schedule).filter(Schedule.is_active.is_(True)).all()
    previous = _get(db, PAUSED_KEY) or {"pipelines": [], "schedules": []}
    # pausing twice keeps the first list too (so "resume previous" brings back everything that was on)
    snapshot = {"pipelines": sorted(set(previous.get("pipelines", [])) | {p.id for p in pipes}),
                "schedules": sorted(set(previous.get("schedules", [])) | {s.id for s in scheds}),
                "at": datetime.now().isoformat(timespec="seconds")}
    for p in pipes:
        p.is_active = False
        scheduler_service.remove_pipeline_job(p.project_id)
    for s in scheds:
        s.is_active = False
        scheduler_service.remove_job(s.id)
    db.commit()
    _put(db, PAUSED_KEY, snapshot)
    stopped_runs = 0
    for proj in db.query(Project).all():
        if pipeline_service.is_pipeline_running(proj.id):
            pipeline_service.request_stop(proj.id)
            stopped_runs += 1
    log_activity(f"⏸ bulk: paused {len(pipes)} pipeline(s) and {len(scheds)} script schedule(s), "
                 f"stopped {stopped_runs} running pipeline(s)")
    return {"detail": f"Paused {len(pipes)} pipeline schedule(s) and {len(scheds)} script schedule(s); "
                      f"stopped {stopped_runs} pipeline(s) that were running."}


@router.post("/pipelines/resume")
def resume_pipelines(mode: str = Query("previous", pattern="^(previous|all)$"), db: Session = Depends(get_db)):
    snapshot = _get(db, PAUSED_KEY)
    if mode == "previous" and not snapshot:
        raise HTTPException(400, "Nothing was paused with “Pause all” — use “Resume all” instead.")
    pq, sq = db.query(PipelineSchedule), db.query(Schedule)
    if mode == "previous":
        pq = pq.filter(PipelineSchedule.id.in_(snapshot.get("pipelines", [])))
        sq = sq.filter(Schedule.id.in_(snapshot.get("schedules", [])))
    resumed_p, resumed_s, bad = 0, 0, []
    for p in pq.all():
        try:
            p.is_active = True
            scheduler_service.add_or_update_pipeline_job(p)
            resumed_p += 1
        except ValueError:
            p.is_active = False
            bad.append(f"pipeline #{p.id} (invalid cron {p.cron_expression!r})")
    for s in sq.all():
        try:
            s.is_active = True
            scheduler_service.add_or_update_job(s)
            resumed_s += 1
        except ValueError:
            s.is_active = False
            bad.append(f"schedule #{s.id} (invalid cron {s.cron_expression!r})")
    db.commit()
    _put(db, PAUSED_KEY, None)
    log_activity(f"▶ bulk: resumed {resumed_p} pipeline(s) and {resumed_s} script schedule(s) ({mode})")
    detail = f"Resumed {resumed_p} pipeline schedule(s) and {resumed_s} script schedule(s)."
    if bad:
        detail += " Skipped: " + "; ".join(bad)
    return {"detail": detail}


# ---------------------------------------------------------------------------
# dashboards
# ---------------------------------------------------------------------------
def _stop_all() -> dict:
    db = SessionLocal()
    try:
        statuses = supervisor_service.all_statuses()
        running = [p for p in db.query(Project).order_by(Project.name)
                   if supervisor_service.state_from_raw(
                       statuses.get(supervisor_service.program_name(p.name), "")) == "RUNNING"]
        previous = _get(db, STOPPED_KEY) or {"projects": []}
        results = []
        for p in running:
            try:
                supervisor_service.stop(p.name)
                p.dashboard_status = "STOPPED"
                results.append({"project": p.name, "ok": True})
            except Exception as exc:  # noqa: BLE001 — keep going with the others
                results.append({"project": p.name, "ok": False, "error": getattr(exc, "detail", str(exc))})
        db.commit()
        stopped_names = [r["project"] for r in results if r["ok"]]
        _put(db, STOPPED_KEY, {"projects": sorted(set(previous.get("projects", [])) | set(stopped_names)),
                               "at": datetime.now().isoformat(timespec="seconds")})
        log_activity(f"⏹ bulk: stopped {len(stopped_names)} dashboard(s)")
        return {"detail": f"Stopped {len(stopped_names)} of {len(running)} running dashboard(s).", "results": results}
    finally:
        db.close()


def _start_all(mode: str) -> dict:
    db = SessionLocal()
    try:
        snapshot = _get(db, STOPPED_KEY)
        if mode == "previous" and not snapshot:
            raise HTTPException(400, "No dashboards were stopped with “Stop all” — use “Start all” instead.")
        projects = db.query(Project).order_by(Project.name).all()
        if mode == "previous":
            wanted = set(snapshot.get("projects", []))
            projects = [p for p in projects if p.name in wanted]
        else:
            projects = [p for p in projects if _has_dashboard(p)]
        statuses = supervisor_service.all_statuses()
        results = []
        for p in projects:
            raw = statuses.get(supervisor_service.program_name(p.name), "")
            if supervisor_service.state_from_raw(raw) == "RUNNING":
                results.append({"project": p.name, "ok": True, "note": "already running"})
                continue
            try:
                start_dashboard(p.id, db)       # same path as the dashboard's own Start button
                results.append({"project": p.name, "ok": True})
            except Exception as exc:  # noqa: BLE001
                results.append({"project": p.name, "ok": False, "error": getattr(exc, "detail", str(exc))})
        # forget the ones that are up again; keep failures remembered so "Start previous" can retry them
        still_down = [r["project"] for r in results if not r["ok"]]
        if mode == "previous" and still_down:
            _put(db, STOPPED_KEY, {"projects": still_down, "at": snapshot.get("at")})
        elif mode == "previous" or not still_down:
            _put(db, STOPPED_KEY, None)
        started = sum(1 for r in results if r["ok"])
        log_activity(f"▶ bulk: started {started} dashboard(s) ({mode})")
        return {"detail": f"{started} of {len(results)} dashboard(s) running.", "results": results}
    finally:
        db.close()


# Dozens of dashboards take minutes: run in the background, the page polls /status.
@router.post("/dashboards/stop")
def stop_dashboards():
    if not bg_tasks.start(TASK, _stop_all):
        raise HTTPException(409, "A bulk dashboard action is already running.")
    return {"detail": "Stopping dashboards in the background…"}


@router.post("/dashboards/start")
def start_dashboards(mode: str = Query("previous", pattern="^(previous|all)$"), db: Session = Depends(get_db)):
    if mode == "previous" and not _get(db, STOPPED_KEY):
        raise HTTPException(400, "No dashboards were stopped with “Stop all” — use “Start all” instead.")
    if not bg_tasks.start(TASK, _start_all, mode):
        raise HTTPException(409, "A bulk dashboard action is already running.")
    return {"detail": "Starting dashboards in the background…"}
