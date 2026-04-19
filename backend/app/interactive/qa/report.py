"""
Run all QA checks against an experience and persist the report.

``run_qa(experience)`` is the single entry point. It:

  1. Builds a fresh manifest via ``assembly.build_manifest``.
  2. Executes every callable from ``checks.all_checks()``.
  3. Aggregates the issues + a verdict (pass/warn/fail).
  4. Persists a row on ``ix_qa_reports`` so the publish flow and
     the studio UI can read the latest report without re-running
     the checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from .. import store
from ..assembly import build_manifest
from ..models import Experience
from .checks import QAIssue, all_checks


@dataclass(frozen=True)
class QASummary:
    """Verdict + counts + issues for one QA run."""

    experience_id: str
    verdict: str  # 'pass' | 'warn' | 'fail'
    issues: List[QAIssue]
    counts: Dict[str, int]
    report_id: str


def _verdict_from_issues(issues: List[QAIssue]) -> str:
    if any(i.get("severity") == "error" for i in issues):
        return "fail"
    if any(i.get("severity") == "warning" for i in issues):
        return "warn"
    return "pass"


def _persist_report(
    experience_id: str, verdict: str, issues: List[QAIssue], counts: Dict[str, int],
) -> str:
    """Insert a row into ix_qa_reports and return its id."""
    store.ensure_schema()
    rid = store.new_id("ixr")
    summary = {"verdict": verdict, "counts": counts}
    with store._conn() as con:
        con.execute(
            """
            INSERT INTO ix_qa_reports (id, experience_id, kind, summary, issues)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                rid, experience_id, "publish_check",
                store._dump_json(summary),
                store._dump_json(issues),
            ),
        )
        con.commit()
    return rid


def run_qa(experience: Experience) -> QASummary:
    """Run every registered check + persist the report."""
    manifest = build_manifest(experience)
    issues: List[QAIssue] = []
    for check in all_checks():
        issues.extend(check(manifest))
    counts = {
        "error": sum(1 for i in issues if i.get("severity") == "error"),
        "warning": sum(1 for i in issues if i.get("severity") == "warning"),
        "info": sum(1 for i in issues if i.get("severity") == "info"),
        "total": len(issues),
    }
    verdict = _verdict_from_issues(issues)
    rid = _persist_report(experience.id, verdict, issues, counts)
    return QASummary(
        experience_id=experience.id,
        verdict=verdict,
        issues=issues,
        counts=counts,
        report_id=rid,
    )


def latest_report(experience_id: str) -> Dict[str, Any]:
    """Fetch the most recent QA report row (raw dict). Returns
    ``{}`` if no report exists yet."""
    store.ensure_schema()
    with store._conn() as con:
        row = con.execute(
            "SELECT * FROM ix_qa_reports WHERE experience_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (experience_id,),
        ).fetchone()
    if not row:
        return {}
    return store.row_to_dict(row, json_fields=("summary", "issues"))
