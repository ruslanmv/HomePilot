"""Timezone-aware background scheduler for HomePilot routines."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from . import service, store


_task: Optional[asyncio.Task] = None


def execution_enabled() -> bool:
    return os.getenv("ROUTINES_EXECUTION_ENABLED", "false").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _parse_time(value: str) -> dt_time:
    try:
        hour, minute = str(value or "08:00").split(":", 1)
        return dt_time(hour=int(hour), minute=int(minute))
    except Exception:
        return dt_time(hour=8, minute=0)


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed
    except Exception:
        return None


def most_recent_occurrence(
    routine: Dict[str, Any],
    now_utc: Optional[datetime] = None,
) -> Optional[datetime]:
    """Return the most recent scheduled UTC instant that is not in the future.

    The routine timezone is authoritative, so DST transitions are handled by
    zoneinfo rather than manual UTC offsets.
    """
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    try:
        tz = ZoneInfo(str(routine.get("timezone") or "UTC"))
    except Exception:
        tz = ZoneInfo("UTC")

    schedule = routine.get("schedule") or {}
    kind = str(schedule.get("type") or "daily")
    created = _parse_iso(str(routine.get("created_at") or ""))
    if created and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    candidate: Optional[datetime] = None

    if kind == "once":
        at = _parse_iso(str(schedule.get("at") or ""))
        if not at:
            return None
        if at.tzinfo is None:
            at = at.replace(tzinfo=tz)
        candidate = at.astimezone(timezone.utc)

    else:
        local_now = now.astimezone(tz)
        clock = _parse_time(str(schedule.get("time") or "08:00"))

        if kind == "daily":
            local_candidate = datetime.combine(local_now.date(), clock, tzinfo=tz)
            if local_candidate > local_now:
                local_candidate -= timedelta(days=1)
            candidate = local_candidate.astimezone(timezone.utc)

        elif kind == "weekly":
            days = {
                int(day)
                for day in (schedule.get("days") or [])
                if isinstance(day, int) or str(day).isdigit()
            }
            if not days:
                return None
            for offset in range(0, 8):
                date = local_now.date() - timedelta(days=offset)
                if date.isoweekday() not in days:
                    continue
                local_candidate = datetime.combine(date, clock, tzinfo=tz)
                if local_candidate <= local_now:
                    candidate = local_candidate.astimezone(timezone.utc)
                    break

    if candidate is None or candidate > now:
        return None
    if created and candidate < created.astimezone(timezone.utc):
        return None
    return candidate


async def tick(now_utc: Optional[datetime] = None) -> Dict[str, int]:
    stats = {"checked": 0, "started": 0, "missed": 0, "skipped": 0}
    if not execution_enabled():
        return stats

    now = now_utc or datetime.now(timezone.utc)
    grace_seconds = max(
        30,
        int(os.getenv("ROUTINES_ON_TIME_GRACE_SECONDS", "90")),
    )

    for routine in store.list_enabled_routines_with_owner():
        stats["checked"] += 1
        occurrence = most_recent_occurrence(routine, now)
        if occurrence is None:
            stats["skipped"] += 1
            continue

        scheduled_for = occurrence.isoformat()
        run_key = f"{routine['id']}:{scheduled_for}"
        if store.get_run_by_key(routine["user_id"], run_key):
            stats["skipped"] += 1
            continue

        age = max(0.0, (now - occurrence).total_seconds())
        catch_up = bool((routine.get("delivery") or {}).get("catch_up", True))

        if age > grace_seconds and not catch_up:
            run, created = store.claim_run(
                routine["user_id"],
                routine["id"],
                scheduled_for=scheduled_for,
                run_key=run_key,
            )
            if created:
                store.finish_run(
                    routine["user_id"],
                    run["id"],
                    status="missed",
                    result_preview="Scheduled time passed while HomePilot was unavailable.",
                    result={
                        "routine_id": routine["id"],
                        "routine_name": routine.get("name") or "Routine",
                    },
                )
                stats["missed"] += 1
            else:
                stats["skipped"] += 1
            continue

        stats["started"] += 1
        await service.execute_routine(
            routine["user_id"],
            routine,
            scheduled_for=scheduled_for,
            run_key=run_key,
        )

    return stats


async def _loop() -> None:
    interval = max(15, int(os.getenv("ROUTINES_SCHEDULER_INTERVAL_SECONDS", "30")))
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[ROUTINES] scheduler tick failed: {exc}")
        await asyncio.sleep(interval)


def start_scheduler() -> Optional[asyncio.Task]:
    global _task
    if not execution_enabled():
        return None
    if _task and not _task.done():
        return _task
    _task = asyncio.get_event_loop().create_task(_loop())
    return _task


async def stop_scheduler() -> None:
    global _task
    if not _task:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    finally:
        _task = None
