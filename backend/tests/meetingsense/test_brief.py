"""The Executive Brief composer: polished wording only when it is grounded, facts never the
model's to set, and a deterministic brief whenever the model is absent or wrong."""

from __future__ import annotations

import asyncio
import json

from app.meetingsense.intelligence import brief
from app.meetingsense.intelligence.schema import (
    ActionItem, Conclusion, Decision, Evidence, MeetingAnalysis, Risk,
)


def analysis() -> MeetingAnalysis:
    ev = lambda sid, t0, quote: [Evidence(segment_id=sid, t0_ms=t0, quote=quote)]  # noqa: E731
    return MeetingAnalysis(
        meeting_id="m", title="Agent debugging sync",
        one_line="The team confirmed the Langfuse move and will test the agent with more annotation tickets.",
        risks=[
            Risk(id="r1", title="Unknown status treated as unregistered", severity="high",
                 detail="The agent skips the DNS check when the domain tool returns unknown.", root_cause="No consecutive lookups",
                 solutions=["Chain the DNS and MX checks"], evidence=ev("s2", 6000, "treats unknown domain status as unregistered")),
            Risk(id="r2", title="MX lookup tool missing in the test environment", severity="medium",
                 detail="The MX record tool is unavailable in the testing environment, blocking validation.",
                 evidence=ev("s7", 44000, "missing MX record tool in the test environment is blocking")),
        ],
        decisions=[
            Decision(id="d1", statement="Move prompt management to Langfuse", status="confirmed",
                     evidence=ev("s4", 22000, "move prompt management to Langfuse")),
            Decision(id="d2", statement="Add an MX record lookup before deciding", status="proposed",
                     evidence=ev("s3", 15000, "add a second lookup against the MX records")),
        ],
        action_items=[
            ActionItem(id="a1", text="Inject fifty annotation tickets into the queue", owner="Ebony", due_text="by Friday",
                       evidence=ev("s5", 30000, "inject fifty annotation tickets")),
            ActionItem(id="a2", text="Ask the business systems team for access to the lookup tools", owner="Vasi",
                       due_text="next week", evidence=ev("s8", 52000, "ask the business systems team")),
        ],
        conclusions=[Conclusion(id="c1", text="Consecutive lookups and Langfuse-managed prompts are the two fixes.",
                                evidence=ev("s2", 6000, "treats unknown"))],
    )


def test_fallback_brief_splits_blockers_buckets_actions_and_counts_sources():
    out = brief.compose_fallback(analysis())
    assert [c.item for c in out.risks] == ["r1"] and [c.item for c in out.blockers] == ["r2"]
    assert out.risks[0].severity == "high" and out.blockers[0].severity == "medium"
    assert {r.item: r.status_label for r in out.decisions} == {"d1": "Selected", "d2": "Proposed"}
    assert [(s.item, s.bucket) for s in out.actions] == [("a1", "This week"), ("a2", "Next steps")]
    assert out.takeaway.startswith("Consecutive lookups") and out.takeaway_items == ["c1"]
    assert out.source_count == 6  # s2, s7, s4, s3, s5, s8 (c1 shares s2)
    assert out.polished is False and out.eyebrow.endswith("Executive brief")


def test_terms_preserved_guards_numbers_products_and_names():
    src = "Inject fifty annotation tickets into the queue by Friday, said Ebony about Langfuse and the DNS check."
    assert brief.terms_preserved("Add fifty tickets to the queue by Friday", src)
    assert not brief.terms_preserved("Add sixty tickets to the queue", src)          # new number
    assert not brief.terms_preserved("Move the pipeline to Kubernetes", src)         # new product (CamelCase-free noun)
    assert not brief.terms_preserved("Ebony and Amy agreed", src)                    # new name
    assert brief.terms_preserved("Missing DNS Verification Tools", src, sentence_case=False)  # title case allowed
    assert not brief.terms_preserved("Missing MX Verification Tools", src, sentence_case=False)  # MX not in source


def test_merge_keeps_grounded_polish_and_refuses_the_rest():
    polished = {
        "eyebrow": "Technical meeting · Executive brief",
        "title": "Domain status fixes and Langfuse prompt management",
        "intro": "The team traced agent failures to unknown domain status handling and agreed to move prompts to Langfuse.",
        "risks": [{"item": "r1", "title": "Ambiguous domain status handling", "summary": "Unknown statuses are treated as unregistered, so the DNS check is skipped.", "note": "No consecutive lookups."}],
        "blockers": [{"item": "r2", "title": "Missing MX lookup tooling", "summary": "The MX record tool is unavailable in the testing environment, so 3 validation runs were lost."}],
        "decisions": [
            {"item": "d1", "option": "Langfuse prompt management", "impact": "Prompt changes without a full redeploy."},
            {"item": "d2", "option": "MX record lookup", "impact": "Selected as the approved path for all lookups."},
            {"item": "d9", "option": "Rewrite in Rust", "impact": "Invented."},
        ],
        "actions": [{"item": "a1", "text": "Inject fifty annotation tickets into the queue"},
                    {"item": "a2", "text": "Request lookup tool access from the business systems team"}],
        "takeaway": {"text": "Chain the DNS and MX checks and move prompt management to Langfuse.", "items": ["r1", "d1"]},
    }
    out = brief.merge(polished, analysis())
    assert out.polished is True and out.eyebrow == "Technical meeting · Executive brief"
    assert out.title == "Domain status fixes and Langfuse prompt management"
    # r1: accepted polish. r2: the invented "3 validation runs" number drops the card back to its own words.
    assert out.risks[0].title == "Ambiguous domain status handling" and out.risks[0].polished
    assert out.blockers[0].item == "r2" and not out.blockers[0].polished
    assert out.blockers[0].title.startswith("MX lookup tool missing")
    # d1 polished; d2 presented a proposal as approved → verified wording; d9 unknown → dropped.
    rows = {r.item: r for r in out.decisions}
    assert set(rows) == {"d1", "d2"}
    assert rows["d1"].polished and rows["d1"].status_label == "Selected"
    assert not rows["d2"].polished and rows["d2"].status == "proposed" and rows["d2"].status_label == "Proposed"
    # Buckets come from the analysis, never the model.
    assert [(s.item, s.bucket, s.polished) for s in out.actions] == [("a1", "This week", True), ("a2", "Next steps", True)]
    assert out.takeaway.startswith("Chain the DNS") and out.takeaway_items == ["r1", "d1"]
    assert any("r2" in n for n in out.notes) and any("d2" in n for n in out.notes)


def test_a_takeaway_cannot_announce_an_unconfirmed_decision():
    polished = {"takeaway": {"text": "The MX record lookup was selected for all domains.", "items": ["d2"]}}
    out = brief.merge(polished, analysis())
    assert out.takeaway.startswith("Consecutive lookups")  # the fallback conclusion
    assert any("takeaway" in n for n in out.notes)


def test_compose_without_a_model_or_with_a_broken_reply_is_the_fallback():
    a = analysis()
    assert asyncio.run(brief.compose(a, call=None)).polished is False

    async def broken(messages, **kw):
        return "not json at all"

    out = asyncio.run(brief.compose(a, call=broken))
    assert out.polished is False and any("did not answer" in n for n in out.notes)

    async def good(messages, **kw):
        assert kw.get("response_format") == "json"
        return json.dumps({"risks": [{"item": "r1", "title": "Ambiguous domain status", "summary": "The DNS check is skipped."}]})

    out = asyncio.run(brief.compose(a, call=good))
    assert out.polished is True and out.risks[0].title == "Ambiguous domain status"
    # Everything the model did not touch keeps the deterministic wording.
    assert out.decisions and out.actions and out.takeaway


def test_extractive_analyses_never_get_polished():
    a = analysis()
    a.degraded = "extractive"

    async def never(messages, **kw):
        raise AssertionError("the composer must not call a model for an extractive analysis")

    assert asyncio.run(brief.compose(a, call=never)).polished is False
