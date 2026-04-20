"""
Tests for the FIX-SLOW-OLLAMA batch:

* PromptLibrary.policy() applies the
  INTERACTIVE_LLM_TIMEOUT_MULTIPLIER env var.
* Unknown / invalid multiplier values fall back to 1.0.
* Multiplier is clamped to [0.1, 10.0].
* autogen_workflow._parse_spine normalises ``next: "str"`` →
  ``next: ["str"]`` so a single-option LLM response doesn't
  trip the validator.
* Missing ``next`` on a non-ending scene defaults to ``[]``
  (the validator will still reject, but the parser stage no
  longer loses the payload on KeyError).
"""
from __future__ import annotations


# ── Timeout multiplier ─────────────────────────────────────────

def test_timeout_multiplier_default_is_one(monkeypatch):
    from app.interactive.prompts import default_library
    monkeypatch.delenv("INTERACTIVE_LLM_TIMEOUT_MULTIPLIER", raising=False)
    pol = default_library().policy("autoplan.classify_mode")
    # YAML value post-FIX-SLOW-OLLAMA is 30.0; no multiplier.
    assert abs(pol.timeout_s - 30.0) < 0.01


def test_timeout_multiplier_applies_to_policy(monkeypatch):
    from app.interactive.prompts import default_library
    monkeypatch.setenv("INTERACTIVE_LLM_TIMEOUT_MULTIPLIER", "3.0")
    pol = default_library().policy("autoplan.classify_mode")
    assert abs(pol.timeout_s - 90.0) < 0.01


def test_timeout_multiplier_reads_live(monkeypatch):
    from app.interactive.prompts import default_library
    lib = default_library()
    monkeypatch.setenv("INTERACTIVE_LLM_TIMEOUT_MULTIPLIER", "2.0")
    first = lib.policy("autoplan.classify_mode").timeout_s
    monkeypatch.setenv("INTERACTIVE_LLM_TIMEOUT_MULTIPLIER", "0.5")
    second = lib.policy("autoplan.classify_mode").timeout_s
    assert second < first


def test_timeout_multiplier_invalid_falls_back(monkeypatch):
    from app.interactive.prompts import default_library
    for bogus in ["not-a-float", "-1", "0", ""]:
        monkeypatch.setenv("INTERACTIVE_LLM_TIMEOUT_MULTIPLIER", bogus)
        pol = default_library().policy("autoplan.classify_mode")
        assert abs(pol.timeout_s - 30.0) < 0.01, bogus


def test_timeout_multiplier_clamps_at_ten(monkeypatch):
    from app.interactive.prompts import default_library
    monkeypatch.setenv("INTERACTIVE_LLM_TIMEOUT_MULTIPLIER", "999")
    pol = default_library().policy("autoplan.classify_mode")
    # 30s base × clamp(10) = 300s
    assert abs(pol.timeout_s - 300.0) < 0.01


# ── Tolerant spine parser ──────────────────────────────────────

def test_spine_parser_coerces_next_string_to_list():
    from app.interactive.planner.autogen_workflow import _parse_spine
    raw = (
        '{"start":"a","scenes":['
        '{"id":"a","kind":"scene","next":"b"},'
        '{"id":"b","kind":"ending"}]}'
    )
    spine = _parse_spine(raw)
    next_a = next(s["next"] for s in spine["scenes"] if s["id"] == "a")
    assert next_a == ["b"]


def test_spine_parser_coerces_choice_labels_string_to_list():
    from app.interactive.planner.autogen_workflow import _parse_spine
    raw = (
        '{"start":"d","scenes":['
        '{"id":"d","kind":"decision","next":["a"],'
        ' "choice_labels":"Only one"},'
        '{"id":"a","kind":"ending"}]}'
    )
    spine = _parse_spine(raw)
    labels = next(s["choice_labels"] for s in spine["scenes"] if s["id"] == "d")
    assert labels == ["Only one"]


def test_spine_parser_defaults_missing_next_to_empty_list():
    from app.interactive.planner.autogen_workflow import _parse_spine
    # Non-ending scene with ``next`` key absent — parser fills
    # with [] so the validator can emit a clear "missing next[]"
    # error rather than KeyError bubbling up through JSON.
    raw = (
        '{"start":"a","scenes":['
        '{"id":"a","kind":"scene"},'
        '{"id":"z","kind":"ending"}]}'
    )
    spine = _parse_spine(raw)
    next_a = next(s["next"] for s in spine["scenes"] if s["id"] == "a")
    assert next_a == []


def test_spine_parser_leaves_valid_lists_alone():
    from app.interactive.planner.autogen_workflow import _parse_spine
    raw = (
        '{"start":"a","scenes":['
        '{"id":"a","kind":"scene","next":["b","c"]},'
        '{"id":"b","kind":"ending"},'
        '{"id":"c","kind":"ending"}]}'
    )
    spine = _parse_spine(raw)
    next_a = next(s["next"] for s in spine["scenes"] if s["id"] == "a")
    assert next_a == ["b", "c"]


def test_spine_parser_preserves_missing_next_on_ending():
    from app.interactive.planner.autogen_workflow import _parse_spine
    # Endings legitimately have no ``next`` — parser must not
    # inject ``[]`` on them (the validator relies on None to
    # differentiate a real ending from a scene that forgot its
    # outbound edge).
    raw = (
        '{"start":"a","scenes":['
        '{"id":"a","kind":"scene","next":"z"},'
        '{"id":"z","kind":"ending"}]}'
    )
    spine = _parse_spine(raw)
    z = next(s for s in spine["scenes"] if s["id"] == "z")
    assert "next" not in z or z.get("next") is None
