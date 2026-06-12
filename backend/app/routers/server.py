"""
Server stats route (Phase 1 subset of the Server Tools page).

Provides the CPU / RAM / disk / uptime widgets on the home dashboard.
APT management and the supervisor process list arrive in Phase 4.
"""
import time

import psutil
from fastapi import APIRouter, Depends

from ..deps import get_current_user

router = APIRouter(
    prefix="/api/server",
    tags=["server"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/stats")
def server_stats():
    """Point-in-time CPU / RAM / disk / uptime snapshot."""
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    uptime_seconds = int(time.time() - psutil.boot_time())

    days, rem = divmod(uptime_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60

    return {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "memory": {
            "percent": memory.percent,
            "used_gb": round(memory.used / 1024**3, 2),
            "total_gb": round(memory.total / 1024**3, 2),
        },
        "disk": {
            "percent": disk.percent,
            "used_gb": round(disk.used / 1024**3, 2),
            "total_gb": round(disk.total / 1024**3, 2),
        },
        "uptime": {
            "seconds": uptime_seconds,
            "human": f"{days}d {hours}h {minutes}m",
        },
    }
