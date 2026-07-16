"""
Scheduler routes: CRUD for cron schedules attached to scripts.
"""
from datetime import datetime

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Schedule, Script, User
from ..schemas import DetailResponse
from ..services import scheduler_service

router = APIRouter(
    prefix="/api/schedules",
    tags=["scheduler"],
    dependencies=[Depends(get_current_user)],
)


class ScheduleCreate(BaseModel):
    script_id: int
    cron_expression: str
    is_active: bool = True


class ScheduleUpdate(BaseModel):
    cron_expression: str | None = None
    is_active: bool | None = None


def _validate_cron(expr: str) -> None:
    try:
        CronTrigger.from_crontab(expr)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {expr!r}")


def _to_out(s: Schedule, db: Session) -> dict:
    script = db.get(Script, s.script_id)
    return {
        "id": s.id,
        "script_id": s.script_id,
        "script_name": f"{script.project.name}/{script.filename}" if script else "?",
        "cron_expression": s.cron_expression,
        "is_active": s.is_active,
        "next_run": scheduler_service.next_run_time(s.id) if s.is_active else None,
        "last_run": script.last_run if script else None,
        "last_status": script.last_status if script else None,
    }


@router.get("")
def list_schedules(db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    schedules = db.query(Schedule).all()
    if not user.is_admin:
        # Schedules of admin-hidden projects are invisible to non-admins
        def visible(s: Schedule) -> bool:
            script = db.get(Script, s.script_id)
            return not (script and script.project and script.project.hidden)
        schedules = [s for s in schedules if visible(s)]
    return [_to_out(s, db) for s in schedules]


@router.post("", status_code=201)
def create_schedule(body: ScheduleCreate, db: Session = Depends(get_db)):
    if db.get(Script, body.script_id) is None:
        raise HTTPException(status_code=404, detail="Script not found")
    _validate_cron(body.cron_expression)

    schedule = Schedule(
        script_id=body.script_id,
        cron_expression=body.cron_expression,
        is_active=body.is_active,
    )
    db.add(schedule)
    # Mirror the cron onto the script row for quick display
    db.query(Script).filter(Script.id == body.script_id).update(
        {"schedule_cron": body.cron_expression}
    )
    db.commit()
    db.refresh(schedule)

    if schedule.is_active:
        scheduler_service.add_or_update_job(schedule)
    return _to_out(schedule, db)


@router.put("/{schedule_id}")
def update_schedule(schedule_id: int, body: ScheduleUpdate, db: Session = Depends(get_db)):
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if body.cron_expression is not None:
        _validate_cron(body.cron_expression)
        schedule.cron_expression = body.cron_expression
    if body.is_active is not None:
        schedule.is_active = body.is_active
    db.commit()
    db.refresh(schedule)

    if schedule.is_active:
        scheduler_service.add_or_update_job(schedule)
    else:
        scheduler_service.remove_job(schedule.id)
    return _to_out(schedule, db)


@router.post("/{schedule_id}/toggle")
def toggle_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    schedule.is_active = not schedule.is_active
    db.commit()
    db.refresh(schedule)

    if schedule.is_active:
        scheduler_service.add_or_update_job(schedule)
    else:
        scheduler_service.remove_job(schedule.id)
    return _to_out(schedule, db)


@router.delete("/{schedule_id}", response_model=DetailResponse)
def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    scheduler_service.remove_job(schedule.id)
    db.query(Script).filter(Script.id == schedule.script_id).update({"schedule_cron": None})
    db.delete(schedule)
    db.commit()
    return DetailResponse(detail="Schedule deleted")
