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
from ..models import Schedule, Script
from .script_runner import run_script

scheduler = AsyncIOScheduler()


def _job_id(schedule_id: int) -> str:
    return f"schedule-{schedule_id}"


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


def start() -> None:
    """Start the scheduler and load all active schedules (called on app startup)."""
    if not scheduler.running:
        scheduler.start()
    db = SessionLocal()
    try:
        for schedule in db.query(Schedule).filter(Schedule.is_active.is_(True)).all():
            try:
                add_or_update_job(schedule)
            except ValueError:
                # Skip malformed cron expressions rather than crash startup
                continue
    finally:
        db.close()
