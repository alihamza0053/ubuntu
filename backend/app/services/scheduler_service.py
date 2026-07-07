"""
APScheduler integration: run project scripts on cron schedules.

A single AsyncIOScheduler runs inside the FastAPI process. On startup we load
every active schedule from the DB and register a cron job. Each job triggers
the same async run_script() used by manual runs, so logs and last-run status
update identically.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..database import SessionLocal
from ..models import PipelineSchedule, Schedule, Script
from . import trash_service
from .pipeline_service import run_pipeline
from .script_runner import run_script

scheduler = AsyncIOScheduler()


def _job_id(schedule_id: int) -> str:
    return f"schedule-{schedule_id}"


def _pipeline_job_id(project_id: int) -> str:
    return f"pipeline-{project_id}"


async def _run_scheduled(script_id: int) -> None:
    """Job body: look up the script and run it."""
    db = SessionLocal()
    try:
        script = db.get(Script, script_id)
        if script is None:
            return
        project_name = script.project.name
        folder, filename = script.folder, script.filename
    finally:
        db.close()
    await run_script(script_id, project_name, folder, filename)


def add_or_update_job(schedule: Schedule) -> None:
    """Register (or replace) the cron job for a schedule row."""
    trigger = CronTrigger.from_crontab(schedule.cron_expression)
    scheduler.add_job(
        _run_scheduled,
        trigger=trigger,
        args=[schedule.script_id],
        id=_job_id(schedule.id),
        replace_existing=True,
    )


def remove_job(schedule_id: int) -> None:
    job = scheduler.get_job(_job_id(schedule_id))
    if job:
        job.remove()


def next_run_time(schedule_id: int):
    job = scheduler.get_job(_job_id(schedule_id))
    return job.next_run_time if job else None


# ---------- Project pipeline jobs ----------

async def _run_pipeline_job(project_id: int) -> None:
    await run_pipeline(project_id)


def add_or_update_pipeline_job(pipe: PipelineSchedule) -> None:
    """Register (or replace) the cron job that runs a project's full pipeline."""
    trigger = CronTrigger.from_crontab(pipe.cron_expression)
    scheduler.add_job(
        _run_pipeline_job,
        trigger=trigger,
        args=[pipe.project_id],
        id=_pipeline_job_id(pipe.project_id),
        replace_existing=True,
    )


def remove_pipeline_job(project_id: int) -> None:
    job = scheduler.get_job(_pipeline_job_id(project_id))
    if job:
        job.remove()


def pipeline_next_run(project_id: int):
    job = scheduler.get_job(_pipeline_job_id(project_id))
    return job.next_run_time if job else None


def _purge_trash() -> None:
    """Hourly job: drop recycle-bin items past the retention window."""
    try:
        trash_service.purge_expired()
    except Exception:
        pass


def start() -> None:
    """Start the scheduler and load all active schedules (called on app startup)."""
    if not scheduler.running:
        scheduler.start()
    # Auto-empty the recycle bin: sweep expired items hourly (and once now).
    scheduler.add_job(_purge_trash, "interval", hours=1, id="trash-purge",
                      replace_existing=True)
    _purge_trash()
    db = SessionLocal()
    try:
        for schedule in db.query(Schedule).filter(Schedule.is_active.is_(True)).all():
            try:
                add_or_update_job(schedule)
            except ValueError:
                continue  # skip malformed cron rather than crash startup
        for pipe in db.query(PipelineSchedule).filter(PipelineSchedule.is_active.is_(True)).all():
            try:
                add_or_update_pipeline_job(pipe)
            except ValueError:
                continue
    finally:
        db.close()
