"""
QA subsystem — automated checks before publish.

Two layers:

  checks.py   Individual ``QACheck`` callables that each return a
              list of issues (dicts with stable ``code`` keys).
              Pure functions over a manifest dict + cfg.
  report.py   ``run_qa(experience)`` runs every registered check,
              aggregates issues + a verdict (``pass`` / ``warn`` /
              ``fail``), and persists the result on
              ``ix_qa_reports``.

Severity model: each issue carries ``severity`` ∈ {info, warning,
error}. ``run_qa`` returns ``fail`` if any error issue is present,
``warn`` if any warning, otherwise ``pass``. The publish flow
refuses to advance an experience to ``status=published`` while
the latest QA report is ``fail``.
"""
from .checks import QACheck, QAIssue, all_checks
from .report import QASummary, run_qa

__all__ = [
    "QACheck",
    "QAIssue",
    "all_checks",
    "QASummary",
    "run_qa",
]
