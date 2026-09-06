"""Trying harder, and saying the right thing when it was not enough (batch V6).

The plan's two acceptance criteria are the first two tests here, verbatim:

* a model that returns noise on the overview and a real answer on a crop produces the answer,
  with no failure text shown;
* when every rung fails, the message names a model to **install**, not one that failed.

Everything else guards the ways a retry ladder goes wrong: throwing away a usable reply because
the judgement was too strict, retrying the model that just failed, running forever, or showing
somebody a transcript of four attempts when they asked what was on their screen.
"""

from __future__ import annotations

import asyncio
import io
import re

import pytest

from app import vision_ladder as vl
from app.vision_ladder import ladder as ld
from app.vision_ladder import usable


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def screenshot(width=3840, height=2160):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (18, 22, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


GOOD = "The terminal shows ModuleNotFoundError: no module named requests, at app.py line 12."
NOISE = "An image of a computer screen."


def fake(replies, *, model="moondream", record=None):
    """An `analyze_image` whose reply depends on which rung is calling.

    `replies` maps a matcher — "overview" or a crop label — to the text it returns.
    """

    async def analyze(**kwargs):
        prompt = kwargs.get("user_prompt") or ""
        which = "overview"
        for label in ("top-left", "top-right", "bottom-left", "bottom-right", "left", "center", "right"):
            if label.replace("-", " ") in prompt:
                which = label
                break
        if record is not None:
            record.append({"which": which, "model": kwargs.get("model")})
        text = replies.get(which, replies.get("*", ""))
        chosen = kwargs.get("model") or model
        return {
            "ok": bool(text),
            "analysis_text": text,
            "error_code": "" if text else "empty_model_response",
            "meta": {"model": chosen, "mode": kwargs.get("mode")},
        }

    return analyze


async def none_installed(_base):
    return None


def ladder(replies, *, installed=none_installed, record=None, environ=None, **kwargs):
    return run(
        vl.analyze_persistently(
            image_bytes=screenshot(),
            upload_path=None,
            model="moondream",
            user_prompt="What does the error say?",
            mode="both",
            analyze=fake(replies, record=record),
            installed=installed,
            environ=environ or {},
            **kwargs,
        )
    )


# ── the two acceptance criteria ─────────────────────────────────────────────


def test_noise_on_the_overview_and_an_answer_on_a_crop_produces_the_answer():
    out = ladder({"overview": NOISE, "top-left": GOOD})
    assert out["ok"] is True
    assert GOOD in out["analysis_text"]


def test_and_shows_the_person_none_of_the_attempts():
    out = ladder({"overview": NOISE, "top-left": GOOD})
    text = out["analysis_text"]
    assert "moondream" not in text.lower()
    assert "sorry" not in text.lower()
    assert "failed" not in text.lower()
    assert "could not" not in text.lower()


def test_when_everything_fails_the_message_names_a_model_to_install():
    out = ladder({"*": ""})
    assert out["ok"] is False
    assert out["error_code"] == "vision_unreadable"
    assert "ollama pull" in out["message"]

    # The suggestion is something to install, and specifically not the model that just failed.
    suggested = re.search(r"ollama pull ([^\s`]+)", out["message"]).group(1)
    assert "moondream" not in suggested


def test_and_does_not_lead_with_a_model_name():
    # The whole point of the copy rule: the first sentence is about the screen, not about a
    # piece of software the user never chose.
    out = ladder({"*": ""})
    first_sentence = out["message"].split(".")[0].lower()
    assert "moondream" not in first_sentence
    assert "ollama" not in first_sentence
    assert "vision model" not in first_sentence


def test_and_says_which_half_worked():
    # "I couldn't read it" and "your computer failed" are very different sentences and only one
    # of them is true: the screenshot was taken and is still on screen. A message that opens by
    # reporting what the model did instead — even generically — is the one this batch replaced.
    out = ladder({"*": ""})
    first_sentence = out["message"].split(".")[0].lower()
    assert "took the screenshot" in first_sentence
    assert "still on screen" in first_sentence


# ── the rungs ───────────────────────────────────────────────────────────────


def test_a_good_overview_never_costs_a_second_call():
    seen: list = []
    out = ladder({"overview": GOOD}, record=seen)
    assert out["analysis_text"] == GOOD
    assert len(seen) == 1
    assert out["meta"]["rung"] == "overview"


def test_each_crop_is_its_own_single_image_request():
    # This is why the ladder works on today's models: V5's gate guards *several images in one
    # request*, and none of these requests carries more than one.
    seen: list = []
    ladder({"overview": NOISE, "bottom-right": GOOD}, record=seen)
    assert seen[0]["which"] == "overview"
    assert [entry["which"] for entry in seen[1:]] == [
        "top-left", "top-right", "bottom-left", "bottom-right",
    ]


def test_readings_from_several_crops_are_stitched_and_labelled():
    # Four crops read separately cannot know they are one screen. Saying where each reading came
    # from is what lets the person, and the chat model above, put them back together.
    out = ladder({"overview": NOISE, "top-left": GOOD, "bottom-right": GOOD + " Twice."})
    assert "[top-left]" in out["analysis_text"]
    assert "[bottom-right]" in out["analysis_text"]
    assert out["meta"]["rung"] == "crops"


def test_a_better_installed_model_is_tried_before_giving_up():
    async def installed(_base):
        return "qwen2.5vl:7b"

    seen: list = []
    out = ladder({"overview": NOISE, "*": NOISE}, installed=installed, record=seen)
    # Nothing usable anywhere, so the alternate ran and its reply was still kept (below).
    assert any(entry["model"] == "qwen2.5vl:7b" for entry in seen)
    assert [r["rung"] for r in out["meta"]["ladder"]][-1] == "alternate-model"


def test_the_model_that_just_failed_is_never_retried_as_the_alternate():
    async def installed(_base):
        return "moondream"

    seen: list = []
    ladder({"*": NOISE}, installed=installed, record=seen)
    assert [entry["model"] for entry in seen].count("moondream") == len(seen)
    assert not any(entry["which"] == "overview" for entry in seen[1:])


# ── never throw away an answer ──────────────────────────────────────────────


def test_the_best_reply_is_kept_even_when_the_judgement_disliked_all_of_them():
    # A wrong judgement must cost a model call, never an answer.
    out = ladder({"*": NOISE})
    assert out["ok"] is True
    assert out["analysis_text"] == NOISE
    assert out["meta"]["degraded"] is True


def test_and_the_person_is_not_told_it_was_second_best():
    out = ladder({"*": NOISE})
    assert "degraded" not in out["analysis_text"]
    assert out["analysis_text"] == NOISE


def test_nothing_installed_at_all_gets_its_own_sentence():
    async def analyze(**_kwargs):
        return {
            "ok": False,
            "error_code": "no_model",
            "analysis_text": "",
            "meta": {"model": None, "mode": "both"},
        }

    out = run(
        vl.analyze_persistently(
            image_bytes=screenshot(),
            upload_path=None,
            analyze=analyze,
            installed=none_installed,
            environ={},
        )
    )
    assert out["error_code"] == "no_vision_model"
    assert "no vision model installed" in out["message"]


# ── it has to stop ──────────────────────────────────────────────────────────


def test_the_budget_stops_new_rungs():
    clock = {"t": 0.0}

    def now():
        clock["t"] += 40.0
        return clock["t"]

    seen: list = []
    out = ladder({"*": NOISE}, record=seen, now=now, environ={"VISION_LADDER_BUDGET_S": "45"})
    assert len(seen) == 1, seen
    assert any(r.get("reason") == "out-of-budget" or r["rung"] == "overview" for r in out["meta"]["ladder"])


def test_the_budget_also_stops_the_ladder_mid_way_through_the_crops():
    """The budget has to bite *inside* the crop rung, not only before it.

    Four crops on a local machine is four model calls, and a ladder that checks the clock once
    and then runs all of them has no budget — it has a suggestion. The clock here is cheap until
    the crops begin and then jumps, which is what a slow first crop actually looks like.
    """
    clock = {"t": 0.0, "calls": 0}

    def now():
        clock["calls"] += 1
        # Free while the overview runs; 30s a call once the crops start.
        clock["t"] += 0.0 if clock["calls"] < 6 else 30.0
        return clock["t"]

    seen: list = []
    out = ladder({"*": NOISE}, record=seen, now=now, environ={"VISION_LADDER_BUDGET_S": "45"})
    crops_run = [entry for entry in seen if entry["which"] != "overview"]
    assert 0 < len(crops_run) < 4, seen
    assert any(record.get("reason") == "out-of-budget" for record in out["meta"]["ladder"])


def test_the_crop_count_is_capped():
    seen: list = []
    ladder({"*": NOISE}, record=seen, environ={"VISION_LADDER_MAX_CROPS": "2"})
    assert len([e for e in seen if e["which"] != "overview"]) == 2


def test_a_rung_that_throws_is_a_rung_that_failed_not_a_500():
    async def explode(**_kwargs):
        raise RuntimeError("ollama went away")

    out = run(
        vl.analyze_persistently(
            image_bytes=screenshot(),
            upload_path=None,
            model="moondream",
            analyze=explode,
            installed=none_installed,
            environ={},
        )
    )
    assert out["ok"] is False
    assert "ollama went away" not in out["message"], "the user is reading a stack trace"


def test_an_image_with_nothing_to_crop_skips_that_rung():
    seen: list = []
    run(
        vl.analyze_persistently(
            image_bytes=screenshot(800, 600),  # inside the budget: nothing was lost to a resize
            upload_path=None,
            model="moondream",
            analyze=fake({"*": NOISE}, record=seen),
            installed=none_installed,
            environ={},
        )
    )
    assert [entry["which"] for entry in seen] == ["overview"]


# ── the judgement ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,reason",
    [
        ("", "empty"),
        ("An image.", "too-short"),
        ("I'm sorry, I can't help with that.", "refusal"),
        ("I cannot see any text in this image.", "blind"),
        ("A screenshot of a computer screen.", "vacuous"),
        ("### ### ### ### ### ### ### ###", "not-language"),
        ("The error says something. " * 5, "repetition"),
    ],
)
def test_the_shapes_a_failed_reading_takes(text, reason):
    ok, why = usable.assess(text)
    assert ok is False
    assert why == reason


@pytest.mark.parametrize(
    "text",
    [
        GOOD,
        "A VS Code window with main.py open; the terminal below reads 'npm ERR! 404 not found'.",
        "Settings, on the Multimodal tab. The model dropdown says llava:7b and Save is greyed out.",
        "The image shows a photograph of a beach at sunset, with three people walking near the water.",
    ],
)
def test_a_real_answer_is_left_alone(text):
    ok, why = usable.assess(text)
    assert ok is True, why


# ── through the route a person actually hits ────────────────────────────────


def test_the_explain_route_answers_from_a_crop_without_saying_it_had_to(monkeypatch):
    """RS1's `/explain` is the reason this batch exists, so the claim is checked there too.

    A unit-tested ladder that the route never calls would be a batch that changed nothing.
    """
    import app.multimodal as mm
    from app.screensense import frames, routes

    frame = frames.store(screenshot(), "share")
    monkeypatch.setattr(mm, "analyze_image", fake({"overview": NOISE, "top-left": GOOD}))

    response = run(routes.explain(routes.ExplainIn(frame_id=frame.frame_id, question="what does it say?")))
    body = response.body.decode()
    assert response.status_code == 200
    assert GOOD in body
    assert "moondream" not in body.split('"meta"')[0]


def test_and_when_it_cannot_it_tells_the_person_what_to_install(monkeypatch):
    import app.multimodal as mm
    from app.screensense import frames, routes

    frame = frames.store(screenshot(), "share")
    monkeypatch.setattr(mm, "analyze_image", fake({"*": ""}))
    monkeypatch.setattr(mm, "_detect_best_vision_model", none_installed)

    response = run(routes.explain(routes.ExplainIn(frame_id=frame.frame_id, question="what does it say?")))
    body = response.body.decode()
    assert "ollama pull" in body
    assert "Multimodal" in body
