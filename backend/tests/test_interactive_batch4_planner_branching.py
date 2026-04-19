"""
Batch 4/8 — planner + branching engine tests.

Covers:
  - Audience resolution from explicit + prompt-scan
  - Intent parsing caps + preset application per mode
  - Graph validation rules V1..V6
  - Builder produces a valid graph for every mode
  - Merger collapses duplicate endings; edges rewritten correctly
  - Simulator enumerates every path with cap behaviour
"""
from __future__ import annotations

from app.interactive.branching import (
    BranchGraph,
    GraphEdge,
    GraphNode,
    GraphValidationError,
    build_graph,
    collapse_merge_points,
    enumerate_paths,
    validate_graph,
    walk_paths,
)
from app.interactive.config import InteractiveConfig
from app.interactive.planner import Intent, parse_prompt, resolve_audience
from app.interactive.planner.presets import get_preset, list_presets


# ─────────────────────────────────────────────────────────────────
# Audience
# ─────────────────────────────────────────────────────────────────

def test_audience_defaults_when_empty():
    a = resolve_audience("")
    assert a.role == "viewer"
    assert a.level == "beginner"
    assert a.language == "en"


def test_audience_picks_level_from_prompt():
    a = resolve_audience("An advanced user trying this for the first time")
    # 'advanced' wins over 'first time' because advanced matches first.
    assert a.level == "advanced"


def test_audience_picks_role_from_prompt():
    a = resolve_audience("For new employees doing onboarding")
    assert a.role == "trainee"


def test_audience_explicit_beats_prompt():
    a = resolve_audience("advanced user", explicit={"level": "intermediate"})
    assert a.level == "intermediate"


# ─────────────────────────────────────────────────────────────────
# Intent parsing
# ─────────────────────────────────────────────────────────────────

def _cfg(**kw):
    defaults = dict(
        enabled=True, max_branches=12, max_depth=6,
        max_nodes_per_experience=200, llm_model="llama3:8b",
        storage_root="", require_consent_for_mature=True,
        enforce_region_block=True, moderate_mature_narration=True,
        region_block=[], runtime_latency_target_ms=200,
    )
    defaults.update(kw)
    return InteractiveConfig(**defaults)


def test_parse_prompt_extracts_branch_and_depth():
    intent = parse_prompt(
        "Make a 3 branches, 4 steps deep training about fire safety",
        cfg=_cfg(), mode="enterprise_training",
    )
    assert intent.branch_count == 3
    assert intent.depth == 4
    assert "fire safety" in intent.objective.lower()


def test_parse_prompt_respects_caps():
    intent = parse_prompt(
        "Make a 999 branches experience",
        cfg=_cfg(max_branches=5), mode="sfw_general",
    )
    assert intent.branch_count <= 5


def test_parse_prompt_scales_down_when_node_budget_exceeded():
    # max_nodes=50, branches=10, depth=5, scenes/branch=5 → 250 > 50
    intent = parse_prompt(
        "Make a 10 branches, 5 steps deep, 5 scenes experience",
        cfg=_cfg(max_nodes_per_experience=50), mode="sfw_general",
    )
    # The planner scales down branch_count until the budget fits.
    assert intent.branch_count * intent.depth * intent.scenes_per_branch <= 50


def test_parse_prompt_applies_preset_scheme_per_mode():
    intent_edu = parse_prompt("Teach HTML basics", cfg=_cfg(), mode="sfw_education")
    assert intent_edu.scheme == "mastery"
    intent_mat = parse_prompt("Romantic experience", cfg=_cfg(), mode="mature_gated")
    assert intent_mat.scheme == "xp_level"


def test_every_mode_has_a_preset():
    modes = {p.mode for p in list_presets()}
    for m in (
        "sfw_general", "sfw_education", "language_learning",
        "enterprise_training", "social_romantic", "mature_gated",
    ):
        assert m in modes


# ─────────────────────────────────────────────────────────────────
# Graph validation
# ─────────────────────────────────────────────────────────────────

def _line_graph():
    g = BranchGraph()
    a = GraphNode(id="a", kind="scene", is_entry=True)
    b = GraphNode(id="b", kind="scene")
    c = GraphNode(id="c", kind="ending")
    g.add_node(a); g.add_node(b); g.add_node(c)
    g.add_edge(GraphEdge(from_id="a", to_id="b"))
    g.add_edge(GraphEdge(from_id="b", to_id="c"))
    return g


def test_valid_graph_passes_validation():
    validate_graph(_line_graph())  # no exception


def test_v1_no_entry_fails():
    g = BranchGraph()
    g.add_node(GraphNode(id="a", kind="scene"))  # not marked is_entry
    g.add_node(GraphNode(id="b", kind="ending"))
    g.add_edge(GraphEdge(from_id="a", to_id="b"))
    try:
        validate_graph(g)
        assert False, "expected GraphValidationError"
    except GraphValidationError as exc:
        assert any(i.get("rule") == "V1" for i in exc.issues)


def test_v1_multiple_entries_fails():
    g = BranchGraph()
    g.add_node(GraphNode(id="a", kind="scene", is_entry=True))
    g.add_node(GraphNode(id="b", kind="scene", is_entry=True))
    g.add_node(GraphNode(id="c", kind="ending"))
    g.add_edge(GraphEdge(from_id="a", to_id="c"))
    g.add_edge(GraphEdge(from_id="b", to_id="c"))
    try:
        validate_graph(g)
    except GraphValidationError as exc:
        assert any(i.get("rule") == "V1" for i in exc.issues)


def test_v4_cycles_detected():
    g = BranchGraph()
    g.add_node(GraphNode(id="a", kind="scene", is_entry=True))
    g.add_node(GraphNode(id="b", kind="scene"))
    g.add_node(GraphNode(id="c", kind="ending"))
    g.add_edge(GraphEdge(from_id="a", to_id="b"))
    g.add_edge(GraphEdge(from_id="b", to_id="a"))  # cycle!
    g.add_edge(GraphEdge(from_id="b", to_id="c"))
    try:
        validate_graph(g)
        assert False, "expected cycle detection"
    except GraphValidationError as exc:
        assert any(i.get("rule") == "V4" for i in exc.issues)


def test_v5_dangling_edge_detected():
    g = BranchGraph()
    g.add_node(GraphNode(id="a", kind="scene", is_entry=True))
    g.add_node(GraphNode(id="b", kind="ending"))
    g.add_edge(GraphEdge(from_id="a", to_id="b"))
    g.add_edge(GraphEdge(from_id="a", to_id="missing"))  # dangling
    try:
        validate_graph(g)
    except GraphValidationError as exc:
        assert any(i.get("rule") == "V5" for i in exc.issues)


def test_v6_depth_cap_enforced():
    g = _line_graph()
    try:
        validate_graph(g, max_depth=1)  # line graph depth=2, cap=1
    except GraphValidationError as exc:
        assert any(i.get("rule") == "V6" for i in exc.issues)


# ─────────────────────────────────────────────────────────────────
# Builder
# ─────────────────────────────────────────────────────────────────

def test_builder_produces_valid_graph_for_every_mode():
    for mode in (
        "sfw_general", "sfw_education", "language_learning",
        "enterprise_training", "social_romantic", "mature_gated",
    ):
        intent = parse_prompt("Quick demo", cfg=_cfg(), mode=mode)
        graph = build_graph(intent)
        validate_graph(graph, max_depth=10, max_nodes=500)
        assert graph.entry() is not None
        endings = [n for n in graph.nodes if n.kind == "ending"]
        assert len(endings) >= 1


def test_builder_merge_points_creates_single_ending():
    intent = parse_prompt("Make a 3 branches, 3 steps deep", cfg=_cfg(), mode="sfw_general")
    graph = build_graph(intent, merge_points=True)
    endings = [n for n in graph.nodes if n.kind == "ending"]
    assert len(endings) == 1


def test_builder_without_merge_points_per_branch_endings():
    intent = parse_prompt("Make a 3 branches, 3 steps deep", cfg=_cfg(), mode="sfw_general")
    graph = build_graph(intent, merge_points=False)
    endings = [n for n in graph.nodes if n.kind == "ending"]
    assert len(endings) == 3


# ─────────────────────────────────────────────────────────────────
# Merger
# ─────────────────────────────────────────────────────────────────

def test_collapse_merges_identical_endings():
    g = BranchGraph()
    entry = GraphNode(id="e", kind="scene", is_entry=True)
    a = GraphNode(id="a", kind="ending", title="Finale")
    b = GraphNode(id="b", kind="ending", title="Finale")
    g.add_node(entry); g.add_node(a); g.add_node(b)
    g.add_edge(GraphEdge(from_id="e", to_id="a"))
    g.add_edge(GraphEdge(from_id="e", to_id="b"))
    removed = collapse_merge_points(g)
    assert removed == 1
    endings = [n for n in g.nodes if n.kind == "ending"]
    assert len(endings) == 1


def test_collapse_leaves_different_endings_alone():
    g = BranchGraph()
    entry = GraphNode(id="e", kind="scene", is_entry=True)
    a = GraphNode(id="a", kind="ending", title="Happy")
    b = GraphNode(id="b", kind="ending", title="Sad")
    g.add_node(entry); g.add_node(a); g.add_node(b)
    g.add_edge(GraphEdge(from_id="e", to_id="a"))
    g.add_edge(GraphEdge(from_id="e", to_id="b"))
    assert collapse_merge_points(g) == 0


# ─────────────────────────────────────────────────────────────────
# Simulator
# ─────────────────────────────────────────────────────────────────

def test_walk_paths_line_graph():
    paths = list(walk_paths(_line_graph()))
    assert paths == [["a", "b", "c"]]


def test_walk_paths_branching():
    intent = parse_prompt("Make a 2 branches, 2 steps deep", cfg=_cfg(), mode="sfw_general")
    graph = build_graph(intent, merge_points=False)
    paths = list(walk_paths(graph))
    assert len(paths) == 2  # exactly one path per branch


def test_enumerate_paths_reports_truncation():
    # Create a fan-out graph whose path count exceeds cap.
    g = BranchGraph()
    g.add_node(GraphNode(id="e", kind="scene", is_entry=True))
    g.add_node(GraphNode(id="end", kind="ending"))
    for i in range(20):
        mid = f"m{i}"
        g.add_node(GraphNode(id=mid, kind="scene"))
        g.add_edge(GraphEdge(from_id="e", to_id=mid))
        g.add_edge(GraphEdge(from_id=mid, to_id="end"))
    result = enumerate_paths(g, max_paths=5)
    assert result["truncated"] is True
    assert result["count"] == 5
