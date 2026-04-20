"""
Tests for ``app.interactive.prompts`` — the YAML prompt library.

Coverage:

* library.yaml index discovery
* Every declared prompt file exists, parses, and exposes the
  four required fields (id, version, system, user_template).
* ``render()`` substitutes declared variables, leaves unknown
  braces literal, and raises on missing variables.
* ``policy()`` returns a typed ``PromptPolicy`` with the fields
  parsed from the YAML.
* Autoplan prompts have the expected shapes (allowed_values on
  classify_mode, response_format=json on the structured ones).
* A hand-built temp library exercises the loader against
  realistic valid + invalid YAML without touching the real
  prompts on disk.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.interactive.prompts import (
    PromptLibrary,
    PromptLibraryError,
    PromptPolicy,
    RenderedPrompt,
    default_library,
)


# ── Real library smoke ───────────────────────────────────────

def test_default_library_lists_every_autoplan_prompt():
    lib = default_library()
    ids = lib.ids()
    for pid in (
        "autoplan.classify_mode",
        "autoplan.extract_topic",
        "autoplan.title",
        "autoplan.brief",
        "autoplan.audience",
        "autoplan.shape",
        "autoplan.seed_intents",
    ):
        assert pid in ids, f"{pid} missing from library index"


def test_every_index_entry_resolves_to_a_parseable_file():
    lib = default_library()
    for pid in lib.ids():
        # render() with declared variables should succeed;
        # grab declared variables from the raw YAML.
        data = lib._load_prompt(pid)  # type: ignore[attr-defined]
        declared = data.get("variables") or []
        vars_ = {v: f"<{v}>" for v in declared}
        rp = lib.render(pid, **vars_)
        assert rp.prompt_id == pid
        assert rp.system.strip(), f"{pid}: empty system prompt"
        assert rp.user.strip(), f"{pid}: empty user template"


def test_classify_mode_policy_enforces_enum():
    policy = default_library().policy("autoplan.classify_mode")
    assert isinstance(policy, PromptPolicy)
    assert set(policy.allowed_values) == {
        "enterprise_training",
        "sfw_education",
        "language_learning",
        "social_romantic",
        "mature_gated",
        "sfw_general",
    }
    assert policy.fallback == "sfw_general"
    assert policy.response_format is None  # plain-text enum, not JSON


def test_structured_prompts_request_json_response():
    lib = default_library()
    for pid in (
        "autoplan.title",
        "autoplan.audience",
        "autoplan.shape",
        "autoplan.seed_intents",
    ):
        assert lib.policy(pid).response_format == "json", (
            f"{pid} should request JSON response_format"
        )


def test_title_and_brief_declare_abort_fallback():
    lib = default_library()
    assert lib.policy("autoplan.title").fallback == "abort"
    assert lib.policy("autoplan.brief").fallback == "abort"


def test_rendering_substitutes_declared_variables():
    rp = default_library().render(
        "autoplan.classify_mode",
        idea="train new sales reps on pricing",
    )
    assert "train new sales reps on pricing" in rp.user
    assert "{idea}" not in rp.user and "{idea}" not in rp.system


def test_rendering_raises_on_missing_variable():
    with pytest.raises(PromptLibraryError, match="missing required variables"):
        default_library().render("autoplan.classify_mode")  # no idea=


def test_unknown_prompt_id_raises():
    with pytest.raises(PromptLibraryError, match="Unknown prompt id"):
        default_library().render("does.not.exist", idea="x")


# ── Temp library edge cases ──────────────────────────────────

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")


def _tmp_lib(root: Path) -> PromptLibrary:
    return PromptLibrary(root=root)


def test_missing_index_raises(tmp_path: Path):
    with pytest.raises(PromptLibraryError, match="index missing"):
        _tmp_lib(tmp_path).ids()


def test_empty_index_raises(tmp_path: Path):
    _write(tmp_path / "library.yaml", "prompts:\n")
    with pytest.raises(PromptLibraryError, match="non-empty 'prompts:'"):
        _tmp_lib(tmp_path).ids()


def test_id_mismatch_between_index_and_file_raises(tmp_path: Path):
    _write(tmp_path / "library.yaml", """
        prompts:
          fake.id: p/a.yaml
    """)
    _write(tmp_path / "p" / "a.yaml", """
        id: different.id
        version: "1.0.0"
        system: "hi"
        user_template: "hi"
    """)
    with pytest.raises(PromptLibraryError, match="does not match"):
        _tmp_lib(tmp_path).render("fake.id")


def test_render_preserves_literal_braces(tmp_path: Path):
    _write(tmp_path / "library.yaml", """
        prompts:
          demo.echo: demo/echo.yaml
    """)
    _write(tmp_path / "demo" / "echo.yaml", """
        id: demo.echo
        version: "1.0.0"
        variables: [idea]
        system: 'Schema: {{"role": str}}'
        user_template: 'Idea: {idea} then {{not_a_var}}'
    """)
    rp = _tmp_lib(tmp_path).render("demo.echo", idea="ship it")
    assert "ship it" in rp.user
    # Double-braces collapse to a single brace pair after format_map.
    assert '{"role": str}' in rp.system
    # Unknown single-brace keys stay literal.
    assert "{not_a_var}" in rp.user


def test_policy_rejects_invalid_shape(tmp_path: Path):
    _write(tmp_path / "library.yaml", """
        prompts:
          demo.bad: demo/bad.yaml
    """)
    _write(tmp_path / "demo" / "bad.yaml", """
        id: demo.bad
        version: "1.0.0"
        system: s
        user_template: u
        validation:
          allowed_values: "not-a-list"
    """)
    with pytest.raises(PromptLibraryError, match="allowed_values"):
        _tmp_lib(tmp_path).policy("demo.bad")


def test_list_variable_is_bullet_joined(tmp_path: Path):
    _write(tmp_path / "library.yaml", """
        prompts:
          demo.list: demo/list.yaml
    """)
    _write(tmp_path / "demo" / "list.yaml", """
        id: demo.list
        version: "1.0.0"
        variables: [items]
        system: s
        user_template: "Items:\\n{items}"
    """)
    rp = _tmp_lib(tmp_path).render("demo.list", items=["one", "two"])
    assert "- one" in rp.user
    assert "- two" in rp.user


def test_rendered_prompt_to_messages_shape():
    rp = RenderedPrompt(
        prompt_id="demo",
        version="1",
        system="sys",
        user="usr",
    )
    msgs = rp.to_messages()
    assert msgs == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
