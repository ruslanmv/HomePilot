"""Searching a meeting, and every meeting (batch MS15, wave W5).

Four claims carry this batch, and three of them are about things *not* happening.

**Project knowledge is untouched.** `vectordb` gained a `namespace` parameter, and the
default has to resolve to the byte-identical collection name it has always produced — a claim
about data already on disk, where being wrong orphans somebody's knowledge base rather than
failing a request. Asserted against a fixed hash rather than against the expression that
produces it, because an assertion written as `f"project_{md5(...)}"` passes for any change
made to both sides at once.

**A meeting is retrieved from, never absorbed (D4).** The meeting vectors live in their own
namespace, so `get_project_document_count`, `query_project_knowledge` and
`delete_project_knowledge` cannot see them. A user who records a call must not watch their
project's document count jump.

**Delete means delete — now in three stores.** A meeting removed from SQLite but left in the
index still answers questions after the user deleted it.

**No Chroma is not a broken meeting.** Every function here returns an empty, honest answer
rather than raising, because an install without the package must record, transcribe, caption
and export exactly as it did before this batch.
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3

import pytest


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("MEETINGSENSE_ENABLED", "MEETINGSENSE_RETENTION"):
        monkeypatch.delenv(name, raising=False)


class Modules:
    def __init__(self):
        import app.meetingsense.ask as ask
        import app.meetingsense.config as config
        import app.meetingsense.retention as retention
        import app.meetingsense.retrieval as retrieval
        import app.meetingsense.session as session
        import app.meetingsense.store as store
        import app.vectordb as vectordb

        self.ask = ask
        self.config = config
        self.retention = retention
        self.retrieval = retrieval
        self.session = session
        self.store = store
        self.vectordb = vectordb


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


class FakeCollection:
    """Enough Chroma to test the decisions around it, and no more.

    Ranking is by shared words, which is not what an embedding does — and does not need to be.
    What is under test is what gets embedded, what gets filtered, how a hit is cited and what
    happens when the store is not there. Whether MiniLM ranks two paragraphs correctly is
    Chroma's business, and stubbing it "properly" would only test the stub.
    """

    def __init__(self):
        self.rows = {}
        self.queries = []

    def upsert(self, *, ids, documents, metadatas):
        for i, d, m in zip(ids, documents, metadatas):
            self.rows[i] = {"document": d, "metadata": dict(m)}

    def delete(self, *, where):
        for key, value in where.items():
            self.rows = {i: r for i, r in self.rows.items() if r["metadata"].get(key) != value}

    def query(self, *, query_texts, n_results, where=None):
        self.queries.append({"query": query_texts[0], "n_results": n_results, "where": where})
        terms = set(query_texts[0].lower().split())
        scored = []
        for row in self.rows.values():
            if where and any(row["metadata"].get(k) != v for k, v in where.items()):
                continue
            hits = len(terms & set(row["document"].lower().split()))
            if hits:
                scored.append((hits, row))
        scored.sort(key=lambda pair: -pair[0])
        picked = scored[:n_results]
        return {
            "documents": [[r["document"] for _, r in picked]],
            "metadatas": [[r["metadata"] for _, r in picked]],
            "distances": [[1.0 / (1 + h) for h, _ in picked]],
        }

    def count(self):
        return len(self.rows)


class FakeChroma:
    def __init__(self):
        self.collections = {}

    def get_or_create_collection(self, *, name, metadata=None):
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]


@pytest.fixture()
def chroma():
    return FakeChroma()


def seg(t0, text, speaker="them", t1=None):
    return {"t0_ms": t0, "t1_ms": t1 if t1 is not None else t0 + 3_000, "text": text, "speaker": speaker}


def add(mods, mid, t0, text, speaker="them"):
    """One segment, through the store's own append-only writer."""
    return mods.store.add_segments(mid, [{"t0_ms": t0, "t1_ms": t0 + 3_000, "text": text, "speaker": speaker}])


def meeting(mods, mid="m1", title="Q3 planning", started=1_700_000_000.0):
    mods.store.create_meeting(conversation_id="c1", meeting_id=mid, title=title, started_at=started)
    return mid


# ── the namespace, and what it protects ─────────────────────────────────────


class TestNamespace:
    def test_the_project_collection_name_has_not_changed(self, modules):
        # Against a fixed hash, not against the expression that builds it: an assertion
        # written as f"project_{md5(...)}" passes for any change made to both sides at once,
        # and the thing at risk is a collection already sitting on somebody's disk.
        assert modules.vectordb.collection_name("proj-1") == "project_dfad4d030baa67dc"
        assert modules.vectordb.collection_name("proj-1", "project") == "project_dfad4d030baa67dc"

    def test_the_default_is_still_project(self, modules):
        assert modules.vectordb.DEFAULT_NAMESPACE == "project"

    def test_a_meeting_never_lands_in_a_project_collection(self, modules, chroma):
        mid = meeting(modules)
        add(modules, mid, 0, "we agreed to hold pricing at forty a seat")
        modules.retrieval.index_meeting(mid, client=chroma)
        # The whole D4 guarantee, as a property of the names: nothing a project function would
        # ever open. `get_project_document_count` opens `project_<hash>` and only that.
        assert [n for n in chroma.collections if n.startswith("project_")] == []
        assert len(chroma.collections) == 1

    def test_the_project_metadata_shape_is_untouched(self, modules, monkeypatch):
        # Written into collections that already exist on disk; a differently-shaped dict would
        # be a second schema for the same records.
        seen = {}

        class Client:
            def get_or_create_collection(self, *, name, metadata=None):
                seen[name] = metadata
                return FakeCollection()

        monkeypatch.setattr(modules.vectordb, "get_chroma_client", lambda: Client())
        modules.vectordb.get_or_create_collection("proj-1")
        modules.vectordb.get_or_create_collection("m1", "meetings")
        assert seen["project_dfad4d030baa67dc"] == {"project_id": "proj-1"}
        assert seen[modules.vectordb.collection_name("m1", "meetings")] == {
            "namespace": "meetings",
            "key": "m1",
        }


# ── what gets embedded ──────────────────────────────────────────────────────


class TestChunks:
    def test_consecutive_segments_become_paragraphs(self, modules):
        # A segment is eight seconds of speech and often half a sentence. Embedded alone it is
        # a fragment that matches nothing, which is the failure this windowing prevents.
        segments = [seg(i * 4_000, "word " * 20) for i in range(12)]
        rows = modules.retrieval.chunks(segments)
        assert 1 < len(rows) < len(segments)
        assert all(row["kind"] == "transcript" for row in rows)

    def test_a_chunk_carries_the_start_of_its_first_segment(self, modules):
        # A hit that cannot be cited to a moment is a hit nobody can check.
        rows = modules.retrieval.chunks([seg(30_000, "we agreed the budget ceiling is four hundred")])
        assert rows[0]["t0_ms"] == 30_000

    def test_filler_is_dropped_rather_than_embedded(self, modules):
        # "Yeah" and "mm-hm" are most of a meeting's segments and none of its content. Each one
        # embedded is a row that can come back instead of an answer.
        rows = modules.retrieval.chunks([seg(0, "yeah"), seg(4_000, "mm-hm"), seg(8_000, "right")])
        assert rows == []

    def test_filler_inside_a_paragraph_is_kept(self, modules):
        # Dropped as a *chunk*, not as words: "yeah, exactly" in the middle of an exchange is
        # part of the passage, and cutting it out would embed a transcript nobody said.
        rows = modules.retrieval.chunks(
            [seg(0, "we should hold pricing at forty a seat"), seg(4_000, "yeah"), seg(8_000, "agreed then")]
        )
        assert len(rows) == 1
        assert "yeah" in rows[0]["text"]

    def test_a_window_spanning_both_speakers_says_both(self, modules):
        rows = modules.retrieval.chunks(
            [seg(0, "what did we settle on", speaker="me"), seg(4_000, "forty a seat", speaker="them")]
        )
        assert rows[0]["speaker"] == "both"

    def test_a_window_from_one_speaker_keeps_them(self, modules):
        rows = modules.retrieval.chunks([seg(0, "we settled on forty a seat", speaker="them")])
        assert rows[0]["speaker"] == "them"

    def test_a_slide_shown_twice_is_embedded_once(self, modules):
        frames = [
            {"t_ms": 1_000, "hash": "abcd", "caption": "The pricing slide."},
            {"t_ms": 60_000, "hash": "abcd", "caption": "The pricing slide."},
            {"t_ms": 90_000, "hash": "efgh", "caption": "The roadmap."},
        ]
        rows = [r for r in modules.retrieval.chunks([], frames) if r["kind"] == "slide"]
        assert [r["text"] for r in rows] == ["The pricing slide.", "The roadmap."]

    def test_an_uncaptioned_slide_is_not_embedded(self, modules):
        # The image is never embedded — captions only (D9). A keyframe with no caption has
        # nothing to search on, and a row of empty text matches every query a little.
        frames = [{"t_ms": 1_000, "hash": "a", "caption": None}, {"t_ms": 2_000, "hash": "b", "caption": "  "}]
        assert modules.retrieval.chunks([], frames) == []

    def test_the_windows_come_out_in_time_order(self, modules):
        segments = [seg(i * 4_000, "word " * 60) for i in range(6)]
        frames = [{"t_ms": 5_000, "hash": "a", "caption": "A slide in the middle."}]
        rows = modules.retrieval.chunks(segments, frames)
        assert [r["t0_ms"] for r in rows] == sorted(r["t0_ms"] for r in rows)


# ── indexing ────────────────────────────────────────────────────────────────


class TestIndexing:
    def test_a_meeting_is_indexed_with_what_a_citation_needs(self, modules, chroma):
        mid = meeting(modules, title="Q3 planning")
        add(modules, mid, 12_000, "we agreed to hold pricing at forty a seat")
        assert modules.retrieval.index_meeting(mid, client=chroma) == 1
        row = list(chroma.collections.values())[0].rows
        meta = list(row.values())[0]["metadata"]
        assert meta["meeting_id"] == mid
        # Denormalised on purpose: a hit is citable without a database read per result, and
        # still citable on an install whose rows have since been deleted.
        assert meta["title"] == "Q3 planning"
        assert meta["t0_ms"] == 12_000

    def test_re_indexing_replaces_rather_than_doubling(self, modules, chroma):
        # Without stable ids, a second stop puts the whole meeting into every search twice.
        mid = meeting(modules)
        add(modules, mid, 0, "we agreed to hold pricing at forty a seat")
        modules.retrieval.index_meeting(mid, client=chroma)
        modules.retrieval.index_meeting(mid, client=chroma)
        assert list(chroma.collections.values())[0].count() == 1

    def test_a_meeting_with_nothing_worth_embedding_writes_nothing(self, modules, chroma):
        mid = meeting(modules)
        add(modules, mid, 0, "yeah")
        assert modules.retrieval.index_meeting(mid, client=chroma) == 0

    def test_no_vector_store_is_zero_rather_than_an_error(self, modules):
        # The shipped state for most installs. "No store" is the suite's default rather than
        # whatever this machine happens to have installed — see `conftest.py`; asserting it
        # from the ambient environment is what made this test pass here and fail in CI.
        mid = meeting(modules)
        add(modules, mid, 0, "we agreed to hold pricing at forty a seat")
        assert modules.retrieval.index_meeting(mid) == 0
        assert modules.retrieval.available() is False

    def test_the_fallback_to_the_real_client_still_exists(self, unstubbed_client, monkeypatch):
        # The reason `unstubbed_client` exists. Everything else in this suite runs with
        # `_client` stubbed to "no store", so without this a `_client` that had quietly
        # stopped calling `get_chroma_client` would leave the whole suite green and every
        # install with no search.
        import app.vectordb as vectordb

        sentinel = object()
        monkeypatch.setattr(vectordb, "get_chroma_client", lambda *a, **k: sentinel)
        assert unstubbed_client() is sentinel

    def test_a_client_that_cannot_be_built_is_no_store_not_a_crash(self, unstubbed_client,
                                                                   monkeypatch):
        import app.vectordb as vectordb

        def angry(*a, **k):
            raise RuntimeError("no chromadb on this install")

        monkeypatch.setattr(vectordb, "get_chroma_client", angry)
        assert unstubbed_client() is None

    def test_an_explicit_client_is_never_second_guessed(self, unstubbed_client, chroma):
        assert unstubbed_client(chroma) is chroma

    def test_a_store_that_raises_does_not_take_the_meeting_with_it(self, modules):
        class Angry:
            def get_or_create_collection(self, **kwargs):
                return self

            def upsert(self, **kwargs):
                raise RuntimeError("the index is locked")

        mid = meeting(modules)
        add(modules, mid, 0, "we agreed to hold pricing at forty a seat")
        assert modules.retrieval.index_meeting(mid, client=Angry()) == 0

    def test_stopping_a_meeting_indexes_it(self, modules, chroma, monkeypatch):
        monkeypatch.setattr(modules.retrieval, "_client", lambda client=None: client or chroma)

        async def scenario():
            session = modules.session.MeetingSession(
                transport=modules.session.ListTransport(),
                config=modules.config.load_config(),
                now=lambda: 0.0,
            )
            await session.start({"conversation_id": "c1", "title": "Q3 planning"})
            add(modules, session.meeting_id, 0, "we agreed to hold pricing at forty a seat")
            await session.stop()
            return session.meeting_id

        mid = run(scenario())
        rows = list(chroma.collections.values())[0].rows
        assert [r["metadata"]["meeting_id"] for r in rows.values()] == [mid]


# ── searching ───────────────────────────────────────────────────────────────


def indexed(mods, chroma, mid, title, started, rows):
    mods.store.create_meeting(conversation_id="c1", meeting_id=mid, title=title, started_at=started)
    for t0, text in rows:
        add(mods, mid, t0, text)
    mods.retrieval.index_meeting(mid, client=chroma)


class TestSearch:
    @pytest.fixture()
    def library(self, modules, chroma, monkeypatch):
        # `ms_search` takes no client — it is the tool signature personas call — so the fake
        # is installed under it rather than passed in.
        monkeypatch.setattr(modules.retrieval, "_client", lambda client=None: client or chroma)
        indexed(modules, chroma, "m1", "Q3 planning", 1_700_000_000.0,
                [(600_000, "we agreed to hold pricing at forty a seat for the enterprise tier")])
        indexed(modules, chroma, "m2", "Vendor review", 1_700_100_000.0,
                [(120_000, "the vendor contract renewal lands in October and needs legal sign off")])
        return chroma

    def test_a_cross_meeting_query_cites_meeting_and_time(self, modules, library):
        # The acceptance criterion for the batch, and the reason the title is denormalised:
        # "meeting a3f9c2… at 00:12:03" is a citation nobody can follow.
        rows = modules.retrieval.ms_search("vendor contract renewal", k=3)
        assert rows
        assert rows[0]["meeting_id"] == "m2"
        assert rows[0]["cite"] == "Vendor review · 00:02:00"

    def test_a_meeting_scoped_query_sees_only_that_meeting(self, modules, library):
        rows = modules.retrieval.search("pricing contract", meeting_id="m1", client=library)
        assert {r["meeting_id"] for r in rows} == {"m1"}
        assert library.collections[
            modules.vectordb.collection_name("all", "meetings")
        ].queries[-1]["where"] == {"meeting_id": "m1"}

    def test_results_come_back_in_time_order_not_score_order(self, modules, library):
        # The same rule MS13 follows: score decides *which* rows, time decides how they are
        # laid out. A model reading an answer out of fragments does better in the order they
        # were said, and so does a reader checking a citation.
        #
        # The best-scoring row is deliberately the *later* one, so a search that returned score
        # order would come back reversed. With the two agreeing, this test passes for an
        # implementation that never sorts at all.
        # The first is padded past CHUNK_WORDS so the two land in different chunks; without
        # that they are one paragraph and there is no ordering to assert.
        early = "an early mention of the vendor and " + ("filler " * 130)
        indexed(modules, library, "m3", "Long one", 1_700_200_000.0,
                [(60_000, early),
                 (900_000, "the vendor contract renewal needs legal review before October")])
        rows = modules.retrieval.search("vendor contract renewal legal review", meeting_id="m3",
                                        client=library, k=5)
        assert len(rows) == 2
        assert [r["t0_ms"] for r in rows] == [60_000, 900_000]

    def test_the_verbatim_window_is_excluded_without_losing_hits(self, modules, chroma):
        # Over-fetched and then filtered. The rows the question matches *best* are deliberately
        # the recent ones — which is the normal case, since a question asked mid-meeting is
        # usually about what was just said — so a k-sized fetch returns nothing but excluded
        # rows and the retrieval tier comes back empty exactly when the meeting is long enough
        # for it to matter.
        old_rows = [(i * 10_000, f"the vendor contract point number {i} and some more words") for i in range(5)]
        recent = [(50_000 + i * 10_000, f"the vendor contract renewal legal review part {i}") for i in range(5)]
        indexed(modules, chroma, "m9", "Long", 1.0, old_rows + recent)
        found = modules.retrieval.search("vendor contract renewal legal", meeting_id="m9", client=chroma,
                                         k=3, exclude_after_ms=50_000)
        assert found
        assert all(r["t0_ms"] < 50_000 for r in found)

    def test_an_empty_question_asks_the_store_nothing(self, modules, library):
        before = len(library.collections[modules.vectordb.collection_name("all", "meetings")].queries)
        assert modules.retrieval.search("   ", client=library) == []
        after = len(library.collections[modules.vectordb.collection_name("all", "meetings")].queries)
        assert before == after

    def test_no_store_searches_to_nothing(self, modules):
        assert modules.retrieval.search("anything") == []
        assert modules.retrieval.ms_search("anything") == []

    def test_a_store_that_raises_searches_to_nothing(self, modules):
        class Angry:
            def get_or_create_collection(self, **kwargs):
                return self

            def query(self, **kwargs):
                raise RuntimeError("index corrupted")

        assert modules.retrieval.search("anything", client=Angry()) == []

    def test_a_malformed_answer_is_survived(self, modules):
        # Chroma returns lists-of-lists and omits `distances` on some paths. An index error
        # here would lose a question the keyword tier could have answered.
        class Odd:
            def get_or_create_collection(self, **kwargs):
                return self

            def query(self, **kwargs):
                return {"documents": [["a passage"]], "metadatas": [[]], "distances": None}

        rows = modules.retrieval.search("passage", client=Odd())
        assert len(rows) == 1
        assert rows[0]["similarity"] is None
        assert rows[0]["t0_ms"] == 0


# ── delete means delete ─────────────────────────────────────────────────────


class TestForget:
    def test_deleting_a_meeting_removes_its_vectors(self, modules, chroma, monkeypatch):
        # A meeting deleted from SQLite but left in the index still answers questions after
        # the user deleted it — the worst available reading of "delete", and one nobody would
        # notice until a persona quoted it back.
        monkeypatch.setattr(modules.retrieval, "_client", lambda client=None: client or chroma)
        indexed(modules, chroma, "m1", "Q3", 1.0, [(0, "we agreed to hold pricing at forty a seat")])
        indexed(modules, chroma, "m2", "Other", 2.0, [(0, "an unrelated pricing conversation entirely")])

        report = modules.retention.delete_meeting("m1")

        assert report["index_cleared"] is True
        remaining = list(chroma.collections.values())[0].rows
        assert {r["metadata"]["meeting_id"] for r in remaining.values()} == {"m2"}

    def test_a_delete_still_succeeds_with_no_vector_store(self, modules):
        # `False` is the correct and complete answer on an install without Chroma, not a
        # failure — and the rows and files must still go. The absence is the suite's default
        # (`conftest.py`), not this machine's package list: in CI, where `requirements.txt`
        # installs chromadb, this test used to reach a real store, clear it, and correctly
        # report `True` — failing on an assertion that was describing the developer's laptop.
        meeting(modules, "m1")
        report = modules.retention.delete_meeting("m1")
        assert report["index_cleared"] is False
        assert modules.store.get_meeting("m1") is None


# ── the ask path (MS13 + MS15) ──────────────────────────────────────────────


class TestFuse:
    def test_it_interleaves_by_rank_rather_than_merging_by_score(self, modules):
        # The two scores share no scale — a cosine distance and a length-normalised term count
        # — so sorting one list by both is arithmetic that means nothing. Each retriever is
        # asked only to rank its own hits, and the budget is spent one from each in turn.
        #
        # The timestamps are chosen so rank order and time order disagree: the output is in
        # time order, so a test whose ranks and times agree would pass for "take the vector
        # list and truncate it", which is the implementation this rules out.
        vector = [{"t0_ms": 400, "text": "v1"}, {"t0_ms": 500, "text": "v2"}, {"t0_ms": 600, "text": "v3"}]
        keyword = [{"t0_ms": 100, "text": "k1"}, {"t0_ms": 200, "text": "k2"}]
        out = modules.ask.fuse(vector, keyword, limit=3)
        assert {r["text"] for r in out} == {"v1", "k1", "v2"}
        assert [r["t0_ms"] for r in out] == [100, 400, 500]

    def test_the_same_moment_found_twice_is_paid_for_once(self, modules):
        vector = [{"t0_ms": 100, "text": "same moment"}]
        keyword = [{"t0_ms": 100, "text": "same moment"}, {"t0_ms": 900, "text": "another"}]
        out = modules.ask.fuse(vector, keyword, limit=5)
        assert [r["t0_ms"] for r in out] == [100, 900]

    def test_either_retriever_alone_still_works(self, modules):
        # The normal case: a meeting where only one of them fires. During a live meeting the
        # vector side is empty, because indexing happens on stop.
        keyword = [{"t0_ms": 1, "text": "k"}]
        assert [r["text"] for r in modules.ask.fuse((), keyword, limit=5)] == ["k"]
        assert [r["text"] for r in modules.ask.fuse(keyword, (), limit=5)] == ["k"]
        assert modules.ask.fuse((), (), limit=5) == []

    def test_the_limit_holds(self, modules):
        vector = [{"t0_ms": i, "text": f"v{i}"} for i in range(10)]
        keyword = [{"t0_ms": 100 + i, "text": f"k{i}"} for i in range(10)]
        assert len(modules.ask.fuse(vector, keyword, limit=4)) == 4

    def test_the_output_is_in_time_order(self, modules):
        vector = [{"t0_ms": 900, "text": "late"}]
        keyword = [{"t0_ms": 100, "text": "early"}]
        assert [r["text"] for r in modules.ask.fuse(vector, keyword, limit=5)] == ["early", "late"]


class TestAskUsesTheIndex:
    def test_an_ended_meeting_reaches_beyond_the_keyword_tier(self, modules, chroma, monkeypatch):
        monkeypatch.setattr(modules.retrieval, "_client", lambda client=None: client or chroma)
        # The passage that answers the question shares no useful word with it — which is
        # exactly the case keyword scoring cannot reach and the batch exists for.
        indexed(
            modules, chroma, "m1", "Q3", 1.0,
            [(10_000, "we will hold at forty a seat for the enterprise tier"),
             (600_000, "and that is everything for today thanks all for coming")],
        )
        seen = {}

        async def call(messages, **kwargs):
            seen["prompt"] = messages[-1]["content"]
            return "Forty a seat [00:00:10]."

        frame = run(modules.ask.answer("m1", "hold forty seat", call=call))
        assert "forty a seat" in seen["prompt"]
        assert frame["cited"] == ["00:00:10"]

    def test_a_live_meeting_is_unaffected_by_a_missing_index(self, modules):
        # MS13's behaviour exactly: indexing happens on stop, so during a meeting the keyword
        # tier is the whole of retrieval and nothing here may raise because of that.
        mid = meeting(modules)
        add(modules, mid, 0, "the legal review is due in October")
        add(modules, mid, 600_000, "anything else before we finish")

        async def call(messages, **kwargs):
            return "October [00:00:00]."

        frame = run(modules.ask.answer(mid, "when is the legal review due", call=call))
        assert frame["cited"] == ["00:00:00"]

    def test_a_vector_store_that_raises_never_loses_the_keyword_answer(self, modules):
        mid = meeting(modules)
        add(modules, mid, 0, "the legal review is due in October")
        add(modules, mid, 600_000, "anything else before we finish")

        def angry(*args, **kwargs):
            raise RuntimeError("index corrupted")

        async def call(messages, **kwargs):
            return "October [00:00:00]."

        frame = run(modules.ask.answer(mid, "when is the legal review due", call=call, vector_search=angry))
        assert frame["cited"] == ["00:00:00"]
