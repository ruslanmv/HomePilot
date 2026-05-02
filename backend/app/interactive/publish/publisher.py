"""
Publish an experience to a channel.

Core contract: ``publish(experience, channel)`` is idempotent with
respect to the manifest digest — re-publishing unchanged content
returns the existing Publication record without writing a new
row.

Publish blocks (returns ``status='blocked'``) if QA verdict is
``fail``. Warnings do NOT block — the author saw them in the UI
and decided to ship anyway.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .. import store
from ..assembly import PackagedExperience, package_experience
from ..errors import PolicyBlockError
from ..models import Experience, Publication
from ..qa import QASummary, run_qa


_KNOWN_CHANNELS = ("web_embed", "studio_preview", "export")


@dataclass(frozen=True)
class PublishResult:
    """Result of a publish attempt."""

    status: str  # 'published' | 'unchanged' | 'blocked'
    channel: str
    publication: Optional[Publication]
    qa: Optional[QASummary]
    detail: str = ""


def _row_to_publication(row: Any) -> Publication:
    d = store.row_to_dict(row, json_fields=("metadata",))
    return Publication(**d)


def _latest_publication(experience_id: str, channel: str) -> Optional[Publication]:
    store.ensure_schema()
    with store._conn() as con:
        row = con.execute(
            "SELECT * FROM ix_publications WHERE experience_id = ? AND channel = ? "
            "ORDER BY version DESC, rowid DESC LIMIT 1",
            (experience_id, channel),
        ).fetchone()
    return _row_to_publication(row) if row else None


def _insert_publication(
    experience_id: str, channel: str, version: int, packaged: PackagedExperience,
) -> Publication:
    store.ensure_schema()
    pid = store.new_id("ixp")
    metadata: Dict[str, Any] = {
        "digest": packaged.digest,
        "manifest_version": packaged.manifest.get("manifest_version"),
        "stats": packaged.manifest.get("stats", {}),
        "manifest": packaged.manifest,
    }
    with store._conn() as con:
        con.execute(
            """
            INSERT INTO ix_publications (
                id, experience_id, channel, manifest_url, version, metadata
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                pid, experience_id, channel,
                f"inline://digest/{packaged.digest}",
                int(version),
                store._dump_json(metadata),
            ),
        )
        # Mark the experience as published.
        con.execute(
            "UPDATE ix_experiences SET status = 'published', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (experience_id,),
        )
        con.commit()
        row = con.execute("SELECT * FROM ix_publications WHERE id = ?", (pid,)).fetchone()
    return _row_to_publication(row)


def publish(experience: Experience, channel: str = "web_embed") -> PublishResult:
    """Publish or re-publish an experience.

    Returns a ``PublishResult`` with a stable ``status`` code the
    HTTP router maps to a user-friendly message. Never raises on a
    blocked publication — returns ``status='blocked'`` instead.
    """
    if channel not in _KNOWN_CHANNELS:
        raise PolicyBlockError(
            f"unknown publish channel: {channel}",
            data={"known_channels": list(_KNOWN_CHANNELS)},
        )

    qa = run_qa(experience)
    if qa.verdict == "fail":
        return PublishResult(
            status="blocked", channel=channel, publication=None,
            qa=qa, detail="QA verdict is 'fail' — fix errors before publishing",
        )

    packaged = package_experience(experience)
    previous = _latest_publication(experience.id, channel)
    if previous is not None:
        prev_digest = (previous.metadata or {}).get("digest")
        if prev_digest == packaged.digest:
            return PublishResult(
                status="unchanged", channel=channel,
                publication=previous, qa=qa,
                detail="manifest digest unchanged since previous publish",
            )
    next_version = (previous.version + 1) if previous else 1
    pub = _insert_publication(experience.id, channel, next_version, packaged)
    return PublishResult(
        status="published", channel=channel,
        publication=pub, qa=qa,
        detail=f"published v{next_version}",
    )


def list_publications(experience_id: str, channel: Optional[str] = None) -> List[Publication]:
    """List publications for an experience, optionally filtered by channel."""
    store.ensure_schema()
    sql = "SELECT * FROM ix_publications WHERE experience_id = ?"
    args: List[Any] = [experience_id]
    if channel:
        sql += " AND channel = ?"
        args.append(channel)
    sql += " ORDER BY version DESC, rowid DESC"
    with store._conn() as con:
        rows = con.execute(sql, tuple(args)).fetchall()
    return [_row_to_publication(r) for r in rows]
