"""Blank or repeated participant ids never reach a Teams room (they had no thumbnail)."""
import importlib
import sys


def test_clean_ids_drops_blank_and_duplicates(app):
    rooms = sys.modules.get("app.teams.rooms") or importlib.import_module("app.teams.rooms")
    assert rooms._clean_ids(["a", "\r\n", " b ", "", None, "a"]) == ["a", "b"]
    assert rooms._clean_ids(None) == []
