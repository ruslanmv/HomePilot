"""Meeting intelligence (MEETINGS_INTELLIGENCE): the typed analysis, its evidence validator,
the deterministic visual spec, the routes, and the rules that nothing is invented and
nothing shows when the flag is off.

No model, no network: a fake model call returns canned JSON; the extractive floor is
exercised with no call at all.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

SEGMENTS = [
    {"id": "s1", "t0_ms": 0, "t1_ms": 6000, "speaker": "Amy", "text": "Welcome everyone, today we cover the domain status agent and the deployment flow."},
    {"id": "s2", "t0_ms": 6000, "t1_ms": 15000, "speaker": "Ebony", "text": "The agent treats unknown domain status as unregistered instead of checking the DNS name servers, and that is a real problem."},
    {"id": "s3", "t0_ms": 15000, "t1_ms": 22000, "speaker": "Amy", "text": "We could add a second lookup against the MX records before deciding."},
    {"id": "s4", "t0_ms": 22000, "t1_ms": 30000, "speaker": "Vasi", "text": "We agreed to move prompt management to Langfuse so changes do not need a full redeploy."},
    {"id": "s5", "t0_ms": 30000, "t1_ms": 38000, "speaker": "Ebony", "text": "I will inject fifty annotation tickets into the queue by Friday so we surface edge cases."},
    {"id": "s6", "t0_ms": 38000, "t1_ms": 44000, "speaker": "Amy", "text": "Who owns the definition of unknown status in the domain tool?"},
]


def _bare_db(tmp_path, monkeypatch):
    import app.meetingsense.library.db as db
    import app.meetingsense.store as store

    dbfile = tmp_path / "intel.sqlite3"

    def _connect():
        con = sqlite3.connect(dbfile)
        con.row_factory = sqlite3.Row
        return con

    monkeypatch.setattr(store, "_connect", _connect)
    db._migrated_paths.clear()
    return db, store


@pytest.fixture()
def intel(tmp_path, monkeypatch):
    import app.meetingsense.library.jobs as jobs
    import app.meetingsense.library.projection as projection
    import app.meetingsense.library.routes as lib_routes

    monkeypatch.delenv("MEETINGSENSE_ENABLED", raising=False)
    monkeypatch.setenv("MEETINGS_LIBRARY_UPGRADE", "1")
    monkeypatch.setenv("MEETINGS_INTELLIGENCE", "1")
    monkeypatch.setenv("MEETINGS_LIBRARY_WORKER", "0")
    monkeypatch.setenv("MEETINGS_LIBRARY_DIR", str(tmp_path / "media"))
    db, store = _bare_db(tmp_path, monkeypatch)
    monkeypatch.setattr(lib_routes, "_viewer", lambda a, s: "")
    monkeypatch.setattr(projection, "_projects_by_id", lambda: {})
    monkeypatch.setattr(projection, "teams_items", lambda: [])

    from app.meetingsense import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    db.ensure_migrated()

    meeting_id = store.create_meeting(conversation_id="c1", project_id=None, title="Agent debugging sync",
                                      source="import", audio_mode="mic", retention="text")
    store.add_segments(meeting_id, [dict(s, seq=i) for i, s in enumerate(SEGMENTS)])
    db.ensure_entry(meeting_id, origin_type="import")

    class Ctx:
        pass

    out = Ctx()
    out.client, out.db, out.store, out.jobs, out.meeting_id = client, db, store, jobs, meeting_id
    return out


def run_jobs(ctx, limit: int = 10):
    states = []
    for _ in range(limit):
        job = ctx.db.lease_next_job()
        if job is None:
            break
        states.append((job["type"], asyncio.run(ctx.jobs.run_job(job))))
    return states


# ── the extractive floor ────────────────────────────────────────────────────


def test_fallback_analysis_cites_its_own_lines_and_says_so():
    from app.meetingsense.intelligence import analyze

    analysis = asyncio.run(analyze.analyse(SEGMENTS, meeting_id="m", meeting_title="Sync", call=None))
    assert analysis.degraded == "extractive"
    # The agreed Langfuse move is a confirmed decision; the MX lookup a proposal.
    statuses = {d.statement[:20]: d.status for d in analysis.decisions}
    assert any(v == "confirmed" and k.startswith("We agreed") for k, v in statuses.items())
    assert any(v == "proposed" and k.startswith("We could") for k, v in statuses.items())
    # The action item carries its due phrase and the speaker as owner.
    action = next(a for a in analysis.action_items if "annotation" in a.text)
    assert action.owner == "Ebony" and action.due_text and "friday" in action.due_text.lower()
    # Every item is its own line, so the validator keeps all of them.
    assert analysis.validator is not None and analysis.validator.dropped == 0
    for item in analysis.decisions + analysis.action_items + analysis.risks + analysis.open_questions:
        assert item.evidence and item.evidence[0].segment_id in {s["id"] for s in SEGMENTS}
    assert any(q.text.endswith("?") for q in analysis.open_questions)


# ── the validator ───────────────────────────────────────────────────────────


def test_validator_drops_a_forged_quote_and_repairs_a_shifted_stamp():
    from app.meetingsense.intelligence.schema import Decision, Evidence, MeetingAnalysis
    from app.meetingsense.intelligence.validate import validate

    analysis = MeetingAnalysis(meeting_id="m", title="t", decisions=[
        Decision(id="d1", statement="Move to Langfuse", status="confirmed",
                 evidence=[Evidence(t0_ms=22000, quote="move prompt management to Langfuse")]),
        Decision(id="d2", statement="Invented", status="confirmed",
                 evidence=[Evidence(t0_ms=22000, quote="we will rewrite everything in Rust next quarter")]),
        Decision(id="d3", statement="Stamp off by one line", status="proposed",
                 evidence=[Evidence(t0_ms=15500, quote="second lookup against the MX records")]),
    ])
    out = validate(analysis, SEGMENTS)
    ids = [d.id for d in out.decisions]
    assert ids == ["d1", "d3"]
    assert out.validator.dropped == 1 and out.validator.kept == 2
    assert out.decisions[1].evidence[0].segment_id == "s3"  # re-anchored to the real line


def test_quote_matching_tolerates_small_differences_but_not_paraphrase():
    from app.meetingsense.intelligence.validate import quote_matches

    line = SEGMENTS[4]["text"]
    assert quote_matches("inject fifty annotation tickets into the queue", line)[0]
    assert quote_matches("Inject 50 annotation ticket into the queue by friday", line)[0]
    assert not quote_matches("we should add more tests for the queue", line)[0]


# ── map / reduce with a fake model ──────────────────────────────────────────


MAP_REPLY = json.dumps({
    "topics": [{"label": "Domain status detection", "summary": "The agent misreads unknown status."}],
    "decisions": [
        {"statement": "Move prompt management to Langfuse", "status": "confirmed",
         "quote": "move prompt management to Langfuse", "t0": "00:00:22"},
        {"statement": "Add an MX record lookup before deciding", "status": "proposed",
         "quote": "add a second lookup against the MX records", "t0": "00:00:15"},
        {"statement": "Rewrite the agent in Rust", "status": "confirmed", "quote": "rewrite the agent in Rust", "t0": "00:00:15"},
    ],
    "risks": [{"title": "Unknown status treated as unregistered", "severity": "high",
               "detail": "The agent skips the DNS check.", "root_cause": "No consecutive lookups",
               "solutions": ["Chain the DNS and MX checks"], "quote": "treats unknown domain status as unregistered", "t0": "00:00:06"}],
    "actions": [{"text": "Inject fifty annotation tickets", "owner": "Ebony", "due_text": "by Friday",
                 "quote": "inject fifty annotation tickets into the queue by Friday", "t0": "00:00:30"}],
    "questions": [{"text": "Who owns the definition of unknown status?", "quote": "Who owns the definition of unknown status",
                   "t0": "00:00:38"}],
})
REDUCE_REPLY = json.dumps({
    "title": "Fixing domain status detection and the deployment flow",
    "one_line": "The team confirmed the Langfuse move and will test the agent with more annotation tickets.",
    "topics": [{"label": "Domain status detection", "summary": "Unknown status is misread.", "from": ["t1"]}],
    "decisions": [{"statement": "Move prompt management to Langfuse", "status": "confirmed", "from": ["d1"]},
                  {"statement": "Add an MX record lookup before deciding", "status": "proposed", "from": ["d2"]},
                  {"statement": "Rewrite the agent in Rust", "status": "confirmed", "from": ["d3"]}],
    "risks": [{"title": "Unknown status treated as unregistered", "severity": "high", "detail": "The agent skips the DNS check.",
               "root_cause": "No consecutive lookups", "solutions": ["Chain the DNS and MX checks"], "from": ["r1"]}],
    "actions": [{"text": "Inject fifty annotation tickets", "owner": "Ebony", "due_text": "by Friday", "from": ["a1"]}],
    "questions": [{"text": "Who owns the definition of unknown status?", "from": ["q1"]}],
    "conclusions": [{"text": "Consecutive lookups and Langfuse-managed prompts are the two fixes.", "from": ["r1", "d1"]}],
})
QUESTIONS_REPLY = json.dumps({"questions": [
    {"text": "What was decided about prompt management?", "kind": "decisions"},
    {"text": "Why does the agent misread unknown domain status?", "kind": "why"},
    {"text": "Who injects the annotation tickets and by when?", "kind": "actions"},
    {"text": "What remains unresolved about the unknown status definition?", "kind": "open"},
]})


def fake_call_factory(record):
    async def call(messages, **kw):
        system = messages[0]["content"]
        record.append({"system": system[:40], **kw})
        if system.startswith("You read one consecutive slice"):
            return MAP_REPLY
        if system.startswith("You merge candidate findings"):
            return REDUCE_REPLY
        if system.startswith("Write the questions"):
            return QUESTIONS_REPLY
        return "{}"
    return call


def test_model_analysis_keeps_only_verifiable_items_and_builds_the_page():
    from app.meetingsense.intelligence import analyze, layout, questions

    calls = []
    analysis = asyncio.run(analyze.analyse(SEGMENTS, meeting_id="m", meeting_title="Sync",
                                           call=fake_call_factory(calls), model="fake"))
    assert analysis.degraded is None
    assert analysis.title.startswith("Fixing domain status")
    statements = {d.statement: d.status for d in analysis.decisions}
    assert statements["Move prompt management to Langfuse"] == "confirmed"
    assert statements["Add an MX record lookup before deciding"] == "proposed"
    assert "Rewrite the agent in Rust" not in statements  # the forged quote was dropped
    assert analysis.validator.dropped == 1
    assert analysis.risks[0].severity == "high" and analysis.risks[0].evidence[0].segment_id == "s2"
    assert analysis.action_items[0].owner == "Ebony"
    assert analysis.conclusions and analysis.conclusions[0].evidence
    # Every model call asked for JSON and declared its budget.
    assert all(c.get("response_format") == "json" and c.get("max_tokens") for c in calls)

    spec = layout.build_spec(analysis, analysis_id="a1")
    types = [b.type for b in spec.blocks]
    assert types[:2] == ["header", "kpi_row"]
    assert {"risk_cards", "decision_list", "comparison_table", "timeline", "callout"} <= set(types)
    for block in spec.blocks:
        for item_id in block.items:
            assert analysis.item(item_id) is not None
    table = next(b for b in spec.blocks if b.type == "comparison_table")
    assert table.columns == ["Decision", "Status", "Said at"] and table.rows[0][1] == "Confirmed"

    qs = asyncio.run(questions.suggest(analysis, call=fake_call_factory([])))
    assert len(qs) == 4 and qs[0].kind == "decisions"


def test_layout_handles_an_empty_analysis():
    from app.meetingsense.intelligence import layout
    from app.meetingsense.intelligence.schema import MeetingAnalysis

    spec = layout.build_spec(MeetingAnalysis(meeting_id="m", title="Empty"))
    assert [b.type for b in spec.blocks] == ["header", "kpi_row"]


# ── routes and the job ──────────────────────────────────────────────────────


def test_routes_answer_404_with_the_flag_off(intel, monkeypatch):
    monkeypatch.setenv("MEETINGS_INTELLIGENCE", "0")
    r = intel.client.get(f"/v1/meetingsense/library/item/{intel.meeting_id}/analysis")
    assert r.status_code == 404
    assert intel.client.post(f"/v1/meetingsense/library/item/{intel.meeting_id}/analysis", json={}).status_code == 404
    assert intel.client.get("/v1/meetingsense/library/schema").status_code == 404
    # The library itself is untouched by the flag.
    assert intel.client.get(f"/v1/meetingsense/library/item/{intel.meeting_id}").status_code == 200


def test_analysis_job_end_to_end_through_the_routes(intel, monkeypatch):
    calls = []
    monkeypatch.setattr(intel.jobs, "_model_call", lambda options: fake_call_factory(calls))

    before = intel.client.get(f"/v1/meetingsense/library/item/{intel.meeting_id}/analysis").json()
    assert before["state"] == "none"

    queued = intel.client.post(f"/v1/meetingsense/library/item/{intel.meeting_id}/analysis", json={})
    assert queued.status_code == 202 and queued.json()["state"] == "pending"
    assert intel.client.get(f"/v1/meetingsense/library/item/{intel.meeting_id}/analysis").json()["state"] == "pending"
    # Queuing twice does not make a second job.
    assert intel.client.post(f"/v1/meetingsense/library/item/{intel.meeting_id}/analysis", json={}).json()["job"]["id"] == queued.json()["job"]["id"]

    assert run_jobs(intel) == [("analyze", "done")]

    body = intel.client.get(f"/v1/meetingsense/library/item/{intel.meeting_id}/analysis").json()
    assert body["state"] == "ready" and body["degraded"] is None
    assert body["analysis"]["decisions"][0]["evidence"][0]["segment_id"] in {"s3", "s4"}
    assert body["visual"]["blocks"][0]["type"] == "header"
    assert len(body["questions"]) == 4 and body["report"]["dropped"] == 1

    visual = intel.client.get(f"/v1/meetingsense/library/item/{intel.meeting_id}/visual").json()
    assert visual["visual"]["analysis_id"] == body["id"]
    assert intel.client.get(f"/v1/meetingsense/library/item/{intel.meeting_id}/questions").json()["questions"][0]["kind"] == "decisions"
    schema = intel.client.get("/v1/meetingsense/library/schema").json()
    assert schema["schema_version"] == 1 and "properties" in schema["analysis"]

    # Action items are first-class rows, and a tick survives a regenerated analysis.
    actions = intel.client.get(f"/v1/meetingsense/library/item/{intel.meeting_id}/actions").json()["actions"]
    assert len(actions) == 1 and actions[0]["status"] == "open"
    patched = intel.client.patch(f"/v1/meetingsense/library/item/{intel.meeting_id}/actions/{actions[0]['item_id']}",
                                 json={"status": "done", "owner": "Ebony S."}).json()["action"]
    assert patched["status"] == "done" and patched["owner"] == "Ebony S."
    intel.client.post(f"/v1/meetingsense/library/item/{intel.meeting_id}/analysis", json={})
    assert run_jobs(intel) == [("analyze", "done")]
    again = intel.client.get(f"/v1/meetingsense/library/item/{intel.meeting_id}/actions").json()["actions"]
    assert again[0]["status"] == "done" and again[0]["owner"] == "Ebony S."
    assert intel.client.get(f"/v1/meetingsense/library/item/{intel.meeting_id}/analysis").json()["versions"] == 2


def test_analysis_without_a_model_is_extractive_not_fake(intel, monkeypatch):
    monkeypatch.setenv("MEETINGS_LIBRARY_PROCESSING", "0")  # no model lane at all
    intel.client.post(f"/v1/meetingsense/library/item/{intel.meeting_id}/analysis", json={})
    assert run_jobs(intel) == [("analyze", "done")]
    body = intel.client.get(f"/v1/meetingsense/library/item/{intel.meeting_id}/analysis").json()
    assert body["state"] == "ready" and body["degraded"] == "extractive"
    assert body["visual"]["blocks"][0]["meta"]["degraded"] == "extractive"
    assert body["questions"]  # templates over the meeting's own items


def test_analysis_needs_a_transcript(intel):
    empty = intel.store.create_meeting(conversation_id="c2", project_id=None, title="Empty", source="import",
                                       audio_mode="mic", retention="text")
    intel.db.ensure_entry(empty, origin_type="import")
    r = intel.client.post(f"/v1/meetingsense/library/item/{empty}/analysis", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_transcript"
    assert intel.client.get(f"/v1/meetingsense/library/item/{empty}/analysis").json()["state"] == "no_transcript"


def test_relayout_rewrites_the_brief_from_the_latest_analysis(intel, monkeypatch):
    monkeypatch.setenv("MEETINGS_LIBRARY_PROCESSING", "0")  # no model: deterministic brief
    url = f"/v1/meetingsense/library/item/{intel.meeting_id}/visual"
    # Nothing to lay out before an analysis exists.
    r = intel.client.post(url, json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_analysis"

    intel.client.post(f"/v1/meetingsense/library/item/{intel.meeting_id}/analysis", json={})
    assert run_jobs(intel) == [("analyze", "done")]
    first = intel.client.get(url).json()["visual"]
    assert first["template"] == "executive_brief"
    assert first["brief"]["source_count"] > 0 and first["brief"]["polished"] is False
    for row in first["brief"]["decisions"]:
        assert row["status_label"] == {"confirmed": "Selected", "proposed": "Proposed", "rejected": "Rejected"}[row["status"]]

    queued = intel.client.post(url, json={})
    assert queued.status_code == 202 and queued.json()["job"]["type"] == "layout"
    # Queuing twice reuses the pending job; running it keeps the same analysis.
    assert intel.client.post(url, json={}).json()["job"]["id"] == queued.json()["job"]["id"]
    assert run_jobs(intel) == [("layout", "done")]
    again = intel.client.get(url).json()["visual"]
    assert again["analysis_id"] == first["analysis_id"]
    assert again["brief"]["source_count"] == first["brief"]["source_count"]


def test_generic_titles_give_way_to_the_analysis_title_but_typed_ones_never_do(intel, monkeypatch):
    from app.meetingsense.library.jobs import generic_title

    assert generic_title("Imported meeting · Oct 10, 12:31")
    assert generic_title("2026_10_15 09∶30∶00")            # the recorder's file name
    assert generic_title("Recording 12") and generic_title("Meeting") and generic_title("")
    assert not generic_title("Meeting about the budget")
    assert not generic_title("Agent debugging sync")

    calls = []
    monkeypatch.setattr(intel.jobs, "_model_call", lambda options: fake_call_factory(calls))
    generic = intel.store.create_meeting(conversation_id="c3", project_id=None, title="Imported meeting · Oct 10, 12:31",
                                         source="import", audio_mode="mic", retention="text")
    intel.store.add_segments(generic, [dict(s, id=f"g{i}", seq=i) for i, s in enumerate(SEGMENTS)])
    intel.db.ensure_entry(generic, origin_type="sync")
    for mid in (generic, intel.meeting_id):
        intel.client.post(f"/v1/meetingsense/library/item/{mid}/analysis", json={})
    assert run_jobs(intel) == [("analyze", "done"), ("analyze", "done")]
    assert intel.store.get_meeting(generic)["title"] == "Fixing domain status detection and the deployment flow"
    assert intel.store.get_meeting(intel.meeting_id)["title"] == "Agent debugging sync"  # a person's title stays

    # Without a model the analysis is extractive and nothing is renamed.
    monkeypatch.setenv("MEETINGS_LIBRARY_PROCESSING", "0")
    plain = intel.store.create_meeting(conversation_id="c4", project_id=None, title="Recording 7",
                                       source="import", audio_mode="mic", retention="text")
    intel.store.add_segments(plain, [dict(s, id=f"p{i}", seq=i) for i, s in enumerate(SEGMENTS)])
    intel.db.ensure_entry(plain, origin_type="sync")
    intel.client.post(f"/v1/meetingsense/library/item/{plain}/analysis", json={})
    assert run_jobs(intel) == [("analyze", "done")]
    assert intel.store.get_meeting(plain)["title"] == "Recording 7"

    # And the switch turns it off entirely.
    monkeypatch.delenv("MEETINGS_LIBRARY_PROCESSING", raising=False)
    monkeypatch.setenv("MEETINGS_AUTO_TITLE", "0")
    kept = intel.store.create_meeting(conversation_id="c5", project_id=None, title="Recording 8",
                                      source="import", audio_mode="mic", retention="text")
    intel.store.add_segments(kept, [dict(s, id=f"k{i}", seq=i) for i, s in enumerate(SEGMENTS)])
    intel.db.ensure_entry(kept, origin_type="sync")
    intel.client.post(f"/v1/meetingsense/library/item/{kept}/analysis", json={})
    assert run_jobs(intel) == [("analyze", "done")]
    assert intel.store.get_meeting(kept)["title"] == "Recording 8"


def test_summary_job_queues_the_analysis_when_the_flag_is_on(intel, monkeypatch):
    async def no_summary(*a, **k):
        return None

    import app.meetingsense.minutes as minutes

    monkeypatch.setattr(minutes, "autogenerate", no_summary)
    intel.db.create_job(intel.meeting_id, "summarize", max_attempts=1, options={})
    states = run_jobs(intel)
    assert states == [("summarize", "done"), ("analyze", "done")]


# ── guardrails fixed alongside ──────────────────────────────────────────────


def test_owned_entry_fails_closed_for_an_empty_viewer(intel):
    import app.meetingsense.library.routes as lib_routes
    from fastapi import HTTPException

    con = intel.store._connect()
    con.execute("UPDATE ms_library_entries SET owner_user_id = 'user-a' WHERE meeting_id = ?", (intel.meeting_id,))
    con.commit()
    con.close()
    assert lib_routes._owned_entry(intel.meeting_id, "user-a")["entry"]["owner_user_id"] == "user-a"
    for viewer in ("", "user-b"):
        with pytest.raises(HTTPException) as exc:
            lib_routes._owned_entry(intel.meeting_id, viewer)
        assert exc.value.status_code == 404


def test_markdown_export_renders_note_items_not_dict_reprs():
    from app.meetingsense import export

    md = export.to_markdown({"title": "T"}, SEGMENTS[:1], notes={"notes": {
        "summary": "Short.", "decisions": [{"text": "Use Langfuse", "t0": 22000}],
        "actions": [{"text": "Inject tickets", "owner": "Ebony", "done": True}], "questions": ["Who owns it?"],
    }})
    assert "- Use Langfuse (00:00:22)" in md
    assert "- Inject tickets (Ebony, done)" in md
    assert "- Who owns it?" in md
    assert "{'text'" not in md
