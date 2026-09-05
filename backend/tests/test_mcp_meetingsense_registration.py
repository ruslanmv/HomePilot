"""MeetingSense in the catalog, and the Teams decision (batch MS22, wave W7).

MS21 built a server; this is the batch that makes anything find it. Four registration points
— the Forge seeder, the gateway list, the server catalog and the virtual-server allow-lists —
and each is a file a human edits, so each is a file a human forgets.

The other half is a decision the batch row offered two ways: build the thin `hp-teams` server
for tier 2, **or** mark tier 2 paused and make the UI say "unavailable" rather than fail at
click time. This takes the second, and the reason is in the catalog: that entry already
declares an external source, so building a local server behind the same id would put two
implementations behind one identifier — and an operator would end up running the one they did
not mean to.

Marking it, though, is only worth anything if something *reads* the mark. The catalog loader
dropped unknown keys on the floor, so these tests check the whole path: the YAML says
unavailable, the API surfaces it, and the install endpoint refuses with the reason rather than
starting a process for a module that does not exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMPLATES = ROOT / "agentic" / "forge" / "templates"


def _yaml(name: str):
    return yaml.safe_load((TEMPLATES / name).read_text())


@pytest.fixture()
def catalog():
    return _yaml("server_catalog.yaml")


def _entry(catalog, server_id: str):
    for group in catalog.values():
        if not isinstance(group, list):
            continue
        for row in group:
            if isinstance(row, dict) and row.get("id") == server_id:
                return row
    return None


# ── the four registration points ────────────────────────────────────────────


class TestRegistered:
    def test_the_seeder_knows_the_server_and_its_port(self):
        from agentic.forge.seed.seed_all import MCP_SERVERS

        rows = {name: (port, desc) for name, port, desc in MCP_SERVERS}
        assert "hp-meetingsense" in rows
        assert rows["hp-meetingsense"][0] == 9107

    def test_no_two_seeded_servers_share_a_port(self):
        # The failure this prevents looks like a broken tool rather than a broken port: Forge
        # registers whichever answered, and the other server's tools quietly vanish.
        from agentic.forge.seed.seed_all import MCP_SERVERS

        ports = [port for _, port, _ in MCP_SERVERS]
        assert len(ports) == len(set(ports)), sorted(p for p in ports if ports.count(p) > 1)

    def test_the_gateway_list_points_at_9107(self):
        rows = {g["name"]: g for g in _yaml("gateways.yaml")["gateways"]}
        assert rows["hp-meetingsense"]["url"] == "http://localhost:9107/rpc"

    def test_the_catalog_lists_it(self, catalog):
        entry = _entry(catalog, "hp-meetingsense")
        assert entry is not None
        assert entry["port"] == 9107
        assert entry["module"] == "agentic.integrations.mcp.meetingsense_server:app"

    def test_the_catalog_says_it_is_write_gated(self, catalog):
        # Four of its ten tools change something. An operator reading the tile should know
        # before installing, not after wondering why `ms.export` refuses.
        assert _entry(catalog, "hp-meetingsense")["write_gated"] is True

    def test_the_virtual_servers_offer_a_read_only_bundle(self):
        rows = {v["name"]: v for v in _yaml("virtual_servers.yaml")["servers"]}
        readonly = rows["hp-meetings-readonly"]
        assert readonly["include_tool_prefixes"] == ["hp.ms."]
        # Excluded here as well as gated at the server: the gate is the operator's decision
        # and this list is the persona's, and a "read-only" suite that could call `ms.export`
        # would be misnamed.
        assert set(readonly["exclude_tool_prefixes"]) == {
            "hp.ms.update_action", "hp.ms.suggest", "hp.ms.set_mode", "hp.ms.export",
        }

    def test_the_read_only_bundle_excludes_exactly_the_gated_tools(self):
        # Written against the server's own list rather than a copy, so a fifth write tool
        # cannot appear in a bundle named read-only.
        from agentic.integrations.mcp.meetingsense.app import register_tools

        gated = {t.name for t in register_tools() if "[write-gated]" in t.description}
        rows = {v["name"]: v for v in _yaml("virtual_servers.yaml")["servers"]}
        assert set(rows["hp-meetings-readonly"]["exclude_tool_prefixes"]) == gated

    def test_every_tool_the_server_offers_starts_with_the_bundle_prefix(self):
        from agentic.integrations.mcp.meetingsense.app import register_tools

        assert all(t.name.startswith("hp.ms.") for t in register_tools())


# ── the chief of staff ──────────────────────────────────────────────────────


class TestChiefOfStaff:
    def test_it_asks_about_meetings_when_the_question_is_about_meetings(self):
        from agentic.integrations.a2a.chief_of_staff_agent import _asks_about_meetings

        for question in ["what did we decide about pricing?",
                         "summarise last week's meetings",
                         "what came out of the standup",
                         "anything from the vendor call?"]:
            assert _asks_about_meetings(question), question

    def test_and_not_when_it_is_not(self):
        # A false positive costs a tool call that returns nothing; a miss costs a briefing
        # with no citation. The list leans towards asking, but not at everything.
        from agentic.integrations.a2a.chief_of_staff_agent import _asks_about_meetings

        for question in ["draft a job description", "what is our runway"]:
            assert not _asks_about_meetings(question), question

    def test_the_briefing_cites_meetings_separately_from_workspace_hits(self, monkeypatch):
        # Meeting rows carry a `meeting · hh:mm:ss` citation and workspace hits do not. A
        # reader who cannot tell them apart cannot check either.
        import asyncio

        import agentic.integrations.a2a.chief_of_staff_agent as agent

        async def fake_invoke(tool, args):
            return "- [Q3 planning · 00:10:00] hold at forty a seat" if tool == "hp.ms.search" else ""

        monkeypatch.setattr(agent, "_try_invoke", fake_invoke)
        out = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            agent.handle_message("what did we decide about pricing in the meeting?", {})
        )
        assert "From your meetings (cited)" in out["text"]
        assert "Q3 planning · 00:10:00" in out["text"]

    def test_a_briefing_with_no_meetings_reads_as_it_did_before(self, monkeypatch):
        # Best-effort, like the workspace search beside it: `hp.ms.search` returns nothing when
        # MeetingSense is not seeded, and nothing about the output should change.
        import asyncio

        import agentic.integrations.a2a.chief_of_staff_agent as agent

        async def nothing(tool, args):
            return ""

        monkeypatch.setattr(agent, "_try_invoke", nothing)
        out = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            agent.handle_message("what did we decide in the meeting?", {})
        )
        assert "From your meetings" not in out["text"]
        assert "I don't have workspace facts yet" in out["text"]

    def test_the_two_copies_of_the_agent_agree(self):
        # The tree carries the agent twice — a package directory and a flat module. Two copies
        # that drift are worse than one in the wrong place, because the bug reports come from
        # the file nobody is editing.
        flat = (ROOT / "agentic/integrations/a2a/chief_of_staff_agent.py").read_text()
        packaged = (ROOT / "agentic/integrations/a2a/chief-of-staff/app.py").read_text()
        assert "_asks_about_meetings" in flat
        assert "_asks_about_meetings" in packaged


# ── the Teams decision ──────────────────────────────────────────────────────


class TestTeamsIsPaused:
    def test_the_catalog_marks_it_unavailable_with_a_reason(self, catalog):
        entry = _entry(catalog, "hp-teams")
        assert entry["availability"] == "unavailable"
        # A reason a person can act on, not a status code. It names the missing thing and says
        # what still works without it.
        assert "teams-mcp-server" in entry["unavailable_reason"]
        assert "record" in entry["unavailable_reason"]

    def test_it_is_still_registered_rather_than_deleted(self, catalog):
        # Paused, not removed: the port is still reserved, the seeder still knows the name,
        # and an operator who has the external repo can still wire it up.
        from agentic.forge.seed.seed_all import MCP_SERVERS

        assert _entry(catalog, "hp-teams") is not None
        assert ("hp-teams", 9106) in [(n, p) for n, p, _ in MCP_SERVERS]

    def test_the_api_surfaces_availability_for_every_entry(self):
        # Always present, so a renderer does not have to know which entries carry the field.
        from app.agentic.server_manager import ServerDef

        plain = ServerDef({"id": "x", "port": 1}).to_dict()
        assert plain["availability"] == "available"
        assert plain["installable"] is True
        assert "unavailable_reason" not in plain

        paused = ServerDef({"id": "y", "port": 2, "availability": "unavailable",
                            "unavailable_reason": "not built"}).to_dict()
        assert paused["installable"] is False
        assert paused["unavailable_reason"] == "not built"

    def test_installing_it_refuses_with_the_reason_rather_than_at_click_time(self, monkeypatch):
        # The whole point of marking it. Without this the endpoint starts a process for a
        # module that does not exist, leaves a dead port behind, and reports a timeout.
        import asyncio

        from app.agentic import server_manager

        manager = server_manager.ServerManager() if hasattr(server_manager, "ServerManager") \
            else server_manager.get_manager()
        started = []
        monkeypatch.setattr(manager, "_start_process", lambda s: started.append(s.id))

        result = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            manager.install("hp-teams", forge_url="http://localhost:4444")
        )
        assert result["ok"] is False
        assert result["availability"] == "unavailable"
        assert "teams-mcp-server" in result["error"]
        # And nothing was started.
        assert started == []

    def test_meetingsense_itself_is_installable(self):
        from app.agentic.server_manager import ServerDef, _load_catalog

        entry = _entry(_load_catalog(), "hp-meetingsense")
        assert ServerDef(entry).installable is True
