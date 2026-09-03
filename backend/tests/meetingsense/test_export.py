"""Reading a meeting back, and taking it out (batch MS6).

The interesting cases here are all about imperfect data, because that is what a real meeting
produces. ``t1`` is ``None`` for every segment when transcription runs through a remote
OpenAI-compatible endpoint — MS1-a, still unbuilt — so an export that only works on measured
timings works on none of those installs. Every test below that mentions ``t1: None`` exists
for that reason and not for tidiness.

The other theme is what a document *claims*. An empty "Decisions" heading says nothing was
decided; a missing one says nothing was recorded. Those are different, and the reader cannot
tell which they are looking at unless the writer is careful.
"""

from __future__ import annotations

import json
import re
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

MS_ENV_VARS = ["MEETINGSENSE_ENABLED", "STT_BASE_URL", "WHISPER_MODEL"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in MS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


class Modules:
    def __init__(self):
        import app.meetingsense.export as export
        import app.meetingsense.finalize as finalize
        import app.meetingsense.routes as routes
        import app.meetingsense.session as session
        import app.meetingsense.store as store

        self.export = export
        self.finalize = finalize
        self.routes = routes
        self.session = session
        self.store = store


@pytest.fixture()
def modules(tmp_path, monkeypatch):
    mods = Modules()
    db = tmp_path / "meetings.sqlite3"

    def _connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(mods.store, "_connect", _connect)
    mods.store.migrate()
    mods.session._SESSIONS.clear()
    return mods


@pytest.fixture()
def client(modules):
    app = FastAPI()
    app.include_router(modules.routes.router)
    return TestClient(app)


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")


MEETING = {
    "id": "m1",
    "title": "Q3 planning",
    "source": "teams",
    "audio_mode": "system+mic",
    "started_at": 1_756_900_000.0,
    "ended_at": 1_756_901_800.0,
}

SEGMENTS = [
    {"t0_ms": 1_000, "t1_ms": 3_400, "speaker": "them", "text": "the launch moves to October"},
    {"t0_ms": 3_500, "t1_ms": 6_000, "speaker": "me", "text": "legal needs to sign off"},
]


# ── clocks ──────────────────────────────────────────────────────────────────


class TestClock:
    def test_it_reads_as_hours_minutes_seconds(self, modules):
        assert modules.export.clock(3_723_000) == "01:02:03"

    def test_srt_carries_milliseconds(self, modules):
        assert modules.export.clock(3_723_456, srt=True) == "01:02:03,456"

    def test_a_missing_time_is_the_start_not_a_crash(self, modules):
        assert modules.export.clock(None) == "00:00:00"

    def test_a_negative_time_is_clamped(self, modules):
        # Nothing should produce one, but a clock that renders "-1:59:59" is worse than one
        # that renders zero, and this is the last place to catch it.
        assert modules.export.clock(-5) == "00:00:00"


class TestSpeakerLabel:
    def test_wire_values_become_words(self, modules):
        # `me` and `them` are the channel convention, not language a reader should meet.
        assert modules.export.speaker_label("me") == "You"
        assert modules.export.speaker_label("them") == "Them"

    def test_an_unlabelled_segment_still_reads(self, modules):
        assert modules.export.speaker_label(None) == "Speaker"


# ── SRT ─────────────────────────────────────────────────────────────────────


SRT_CUE = re.compile(
    r"^(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.+)$", re.MULTILINE
)


def parse_srt(text):
    return SRT_CUE.findall(text)


class TestSrt:
    def test_it_produces_valid_cues(self, modules):
        cues = parse_srt(modules.export.to_srt(SEGMENTS))
        assert [c[0] for c in cues] == ["1", "2"]
        assert cues[0][1] == "00:00:01,000"
        assert cues[0][2] == "00:00:03,400"
        assert cues[0][3] == "Them: the launch moves to October"

    def test_an_unmeasured_end_borrows_the_next_start(self, modules):
        # A real bound rather than a guess: the speaker had certainly stopped by the time the
        # next one started.
        segments = [
            {"t0_ms": 1_000, "t1_ms": None, "text": "first"},
            {"t0_ms": 4_000, "t1_ms": None, "text": "second"},
        ]
        cues = parse_srt(modules.export.to_srt(segments))
        assert cues[0][2] == "00:00:04,000"

    def test_the_last_unmeasured_segment_gets_a_fixed_span(self, modules):
        # Nothing bounds it, so a length is assumed — and the assumption is visible here
        # rather than hidden in a renderer.
        segments = [{"t0_ms": 1_000, "t1_ms": None, "text": "only"}]
        cues = parse_srt(modules.export.to_srt(segments))
        assert cues[0][2] == "00:00:03,000"

    def test_a_measured_end_beats_the_next_start(self, modules):
        # Order of preference matters: taking the next segment's start first would stretch a
        # two-second sentence across a thirty-second silence.
        segments = [
            {"t0_ms": 0, "t1_ms": 2_000, "text": "brief"},
            {"t0_ms": 30_000, "t1_ms": 31_000, "text": "much later"},
        ]
        cues = parse_srt(modules.export.to_srt(segments))
        assert cues[0][2] == "00:00:02,000"

    def test_a_zero_length_cue_is_widened(self, modules):
        # Players silently drop cues shorter than a frame or two, so a rounding accident
        # becomes an invisible subtitle rather than a short one.
        segments = [{"t0_ms": 5_000, "t1_ms": 5_000, "text": "blink"}]
        cues = parse_srt(modules.export.to_srt(segments))
        assert cues[0][1] != cues[0][2]

    def test_blank_segments_do_not_become_empty_cues(self, modules):
        segments = [{"t0_ms": 0, "t1_ms": 1_000, "text": "   "}, {"t0_ms": 1_000, "t1_ms": 2_000, "text": "real"}]
        cues = parse_srt(modules.export.to_srt(segments))
        assert len(cues) == 1
        # And the numbering has no hole in it.
        assert cues[0][0] == "1"

    def test_a_meeting_with_nothing_in_it_exports_empty_rather_than_broken(self, modules):
        assert modules.export.to_srt([]) == ""


# ── Markdown ────────────────────────────────────────────────────────────────


class TestMarkdown:
    def test_it_leads_with_the_meeting(self, modules):
        text = modules.export.to_markdown(MEETING, SEGMENTS)
        assert text.startswith("# 🎙 Q3 planning")
        assert "teams" in text
        assert "00:30:00 long" in text

    def test_the_transcript_carries_times_and_speakers(self, modules):
        text = modules.export.to_markdown(MEETING, SEGMENTS)
        assert "`00:00:01` **Them** the launch moves to October" in text
        assert "`00:00:03` **You** legal needs to sign off" in text

    def test_an_empty_transcript_says_so(self, modules):
        # An empty section invites the reader to assume the export broke, when the honest
        # answer is usually that nothing was transcribed.
        assert "*No transcript was recorded.*" in modules.export.to_markdown(MEETING, [])

    def test_notes_are_rendered_when_there_are_any(self, modules):
        notes = {"json": json.dumps({"summary": "Short one.", "decisions": ["Ship in October"]})}
        text = modules.export.to_markdown(MEETING, SEGMENTS, (), notes)
        assert "## Summary" in text and "Short one." in text
        assert "## Decisions" in text and "- Ship in October" in text

    def test_an_empty_section_is_omitted_rather_than_left_blank(self, modules):
        # "Decisions" with nothing under it claims nothing was decided. A missing heading
        # claims nothing was recorded. They are different, and the reader cannot tell which
        # they are looking at unless the writer is careful.
        notes = {"json": json.dumps({"summary": "Just a summary.", "decisions": []})}
        text = modules.export.to_markdown(MEETING, SEGMENTS, (), notes)
        assert "## Summary" in text
        assert "## Decisions" not in text

    def test_unreadable_notes_do_not_take_the_export_down(self, modules):
        text = modules.export.to_markdown(MEETING, SEGMENTS, (), {"json": "{not json"})
        assert "## Transcript" in text

    def test_slides_appear_with_their_times(self, modules):
        frames = [{"t_ms": 65_000, "url": "/files/s1.png", "caption": "Roadmap"}]
        text = modules.export.to_markdown(MEETING, SEGMENTS, frames)
        assert "`00:01:05` Roadmap" in text

    def test_an_uncaptioned_slide_says_which_it_is(self, modules):
        # Vision may be unconfigured. "(not captioned)" is a different statement from an empty
        # caption, and the first one tells the reader nothing is broken.
        frames = [{"t_ms": 1_000, "url": "/files/s1.png", "caption": None}]
        assert "(not captioned)" in modules.export.to_markdown(MEETING, SEGMENTS, frames)

    def test_a_meeting_with_no_title_still_has_a_heading(self, modules):
        assert modules.export.to_markdown({"started_at": 1.0}, []).startswith("# 🎙 Meeting")


class TestJson:
    def test_it_carries_everything(self, modules):
        body = modules.export.to_json(MEETING, SEGMENTS)
        assert body["meeting"]["title"] == "Q3 planning"
        assert len(body["segments"]) == 2

    def test_an_unmeasured_end_stays_unmeasured(self, modules):
        # The other two formats have to put something on screen; a data export does not, and
        # inventing an end time hands the next tool a measurement nobody made.
        body = modules.export.to_json(MEETING, [{"t0_ms": 0, "t1_ms": None, "text": "x"}])
        assert body["segments"][0]["t1_ms"] is None


class TestFilename:
    def test_it_names_the_meeting_and_the_day(self, modules):
        assert modules.export.filename(MEETING, "md") == "Q3-planning-2025-09-03.md"

    def test_it_strips_what_a_filesystem_would_refuse(self, modules):
        name = modules.export.filename({**MEETING, "title": "Q3/Q4: plan?"}, "srt")
        assert "/" not in name and ":" not in name and "?" not in name
        assert name.endswith(".srt")


# ── the routes ──────────────────────────────────────────────────────────────


def seed(modules, **overrides):
    meeting_id = modules.store.create_meeting(
        conversation_id="conv-1", title="Q3 planning", source="teams", retention="text", **overrides
    )
    modules.store.add_segments(meeting_id, [{**s, "seq": i + 1} for i, s in enumerate(SEGMENTS)])
    return meeting_id


class TestReadRoute:
    def test_it_returns_everything_the_card_needs(self, client, enabled, modules):
        meeting_id = seed(modules)
        body = client.get(f"/v1/meetingsense/{meeting_id}").json()
        assert body["meeting"]["title"] == "Q3 planning"
        assert len(body["segments"]) == 2
        assert body["keyframes"] == []
        assert body["live"] is False

    def test_a_missing_meeting_is_a_404(self, client, enabled):
        assert client.get("/v1/meetingsense/nope").status_code == 404

    def test_it_is_a_404_while_the_flag_is_off(self, client, modules):
        meeting_id = seed(modules)
        # Same answer as a meeting that does not exist, on purpose: the status endpoint is
        # where a client asks whether the feature exists, and answering it again here would
        # let a caller tell a real id from a fabricated one on an install that never enabled it.
        assert client.get(f"/v1/meetingsense/{meeting_id}").status_code == 404

    def test_it_survives_an_install_with_no_tables(self, client, enabled, modules, monkeypatch):
        def boom():
            raise RuntimeError("no such table: ms_meetings")

        monkeypatch.setattr(modules.store, "_connect", boom)
        assert client.get("/v1/meetingsense/whatever").status_code == 404


class TestExportRoute:
    def test_markdown_is_the_default(self, client, enabled, modules):
        response = client.get(f"/v1/meetingsense/{seed(modules)}/export")
        assert response.status_code == 200
        assert response.text.startswith("# 🎙 Q3 planning")

    def test_srt_validates(self, client, enabled, modules):
        response = client.get(f"/v1/meetingsense/{seed(modules)}/export?fmt=srt")
        cues = parse_srt(response.text)
        assert len(cues) == 2

    def test_json_round_trips(self, client, enabled, modules):
        body = client.get(f"/v1/meetingsense/{seed(modules)}/export?fmt=json").json()
        assert len(body["segments"]) == 2

    def test_a_meeting_with_no_measured_ends_exports_without_error(self, client, enabled, modules):
        # The remote-STT install: every t1 is None. This is the case that would break an
        # exporter written only against local Whisper, and it is most of the installs that
        # cannot debug it.
        meeting_id = modules.store.create_meeting(conversation_id="c", title="Remote", retention="text")
        modules.store.add_segments(
            meeting_id,
            [{"t0_ms": 0, "t1_ms": None, "text": "one", "seq": 1},
             {"t0_ms": 4_000, "t1_ms": None, "text": "two", "seq": 2}],
        )
        for fmt in ("md", "srt", "json"):
            assert client.get(f"/v1/meetingsense/{meeting_id}/export?fmt={fmt}").status_code == 200

    def test_an_unknown_format_is_refused_by_name(self, client, enabled, modules):
        response = client.get(f"/v1/meetingsense/{seed(modules)}/export?fmt=docx")
        assert response.status_code == 400
        assert "md" in response.json()["detail"]

    def test_a_download_is_named_after_the_meeting(self, client, enabled, modules):
        response = client.get(f"/v1/meetingsense/{seed(modules)}/export?fmt=md")
        assert "Q3-planning" in response.headers["content-disposition"]

    def test_export_is_a_404_while_the_flag_is_off(self, client, modules):
        assert client.get(f"/v1/meetingsense/{seed(modules)}/export").status_code == 404


# ── what the meeting leaves in the chat ─────────────────────────────────────


class TestFinalize:
    def test_the_title_is_the_first_line(self, modules):
        # HomePilot has no conversations table: History labels a conversation with its last
        # message. The meeting message is that last message, so the D5 title has to lead it —
        # writing a title column instead would set a value nothing reads.
        body = modules.finalize.meeting_message(MEETING, SEGMENTS)
        assert body.splitlines()[0] == "[Meeting] 🎙 Q3 planning · teams · 2025-09-03"

    def test_it_reads_as_plain_text_without_the_card(self, modules):
        # A client that has never heard of MeetingSense — an export, another persona reading
        # the conversation later — should see an account of the meeting, not a marker.
        body = modules.finalize.meeting_message(MEETING, SEGMENTS)
        assert "the launch moves to October" in body
        assert "00:30:00" in body

    def test_a_long_meeting_is_previewed_not_dumped(self, modules):
        segments = [{"t0_ms": i * 1000, "text": f"line {i}"} for i in range(50)]
        body = modules.finalize.meeting_message(MEETING, segments)
        assert "… and 44 more." in body
        assert "line 44" not in body

    def test_a_silent_meeting_says_so(self, modules):
        assert "Nothing was transcribed." in modules.finalize.meeting_message(MEETING, [])

    def test_slides_are_counted(self, modules):
        body = modules.finalize.meeting_message(MEETING, SEGMENTS, [{"t_ms": 1, "url": "/f/1.png"}])
        assert "1 slide" in body

    def test_stopping_a_meeting_writes_it_into_the_conversation(self, modules, monkeypatch):
        written = []
        import app.storage as storage

        monkeypatch.setattr(storage, "add_message", lambda *a, **k: written.append((a, k)))
        meeting_id = seed(modules)
        assert modules.finalize.finalize_meeting(meeting_id) is not None
        assert len(written) == 1
        assert written[0][0][1] == "assistant"
        assert written[0][0][2].startswith("[Meeting]")

    def test_a_meeting_with_no_conversation_writes_nothing(self, modules, monkeypatch):
        written = []
        import app.storage as storage

        monkeypatch.setattr(storage, "add_message", lambda *a, **k: written.append(a))
        meeting_id = modules.store.create_meeting(conversation_id="", retention="text")
        assert modules.finalize.finalize_meeting(meeting_id) is None
        assert written == []

    def test_a_failure_to_write_never_breaks_the_stop(self, modules, monkeypatch):
        # The transcript is already in the store, which is the part that cannot be
        # reconstructed. Losing the summary message is a nuisance; losing the meeting is not.
        import app.storage as storage

        def boom(*a, **k):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(storage, "add_message", boom)
        assert modules.finalize.finalize_meeting(seed(modules)) is None
