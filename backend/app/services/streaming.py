"""
Shared async helpers for streaming subprocess output and tailing log files
over WebSockets.

Used by: terminal single-run, apt manager, live log viewer, script runner.
All commands are passed as argument lists — never shell strings with raw
user input.
"""
import asyncio
from pathlib import Path
from typing import Awaitable, Callable, Sequence

# An async callback that receives one output line at a time
LineCallback = Callable[[str], Awaitable[None]]


async def stream_command(cmd: Sequence[str], on_line: LineCallback,
                         cwd: str | None = None) -> int:
    """
    Run `cmd` (argument list), stream combined stdout/stderr line-by-line to
    `on_line`, and return the process exit code.

    If `on_line` raises (e.g. the client disconnected) streaming stops but the
    process is allowed to finish.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        await on_line(f"[serverhub] command not found: {exc}")
        return 127

    assert process.stdout is not None
    deliver = True
    while True:
        raw = await process.stdout.readline()
        if not raw:
            break
        if deliver:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            try:
                await on_line(line)
            except Exception:
                deliver = False  # client gone; drain quietly
    return await process.wait()


async def run_command(cmd: Sequence[str], cwd: str | None = None,
                      timeout: int = 60) -> tuple[int, str]:
    """Run `cmd` to completion and return (exit_code, combined_output)."""
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        return 124, "[serverhub] command timed out"
    return process.returncode, out.decode("utf-8", errors="replace")


async def tail_file(path: Path, on_line: LineCallback, backlog: int = 50,
                    poll: float = 0.5) -> None:
    """
    `tail -f` a file: send the last `backlog` lines, then stream appended
    lines as they are written. Waits for the file to appear if missing.
    Loops until the caller's `on_line` raises (client disconnect).
    """
    while not path.is_file():
        await on_line("[serverhub] waiting for log file...")
        await asyncio.sleep(2)

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
        for line in lines[-backlog:]:
            await on_line(line.rstrip("\n"))
        while True:
            line = fh.readline()
            if line:
                await on_line(line.rstrip("\n"))
            else:
                await asyncio.sleep(poll)
