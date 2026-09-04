"""Shared fixtures for the MeetingSense suite.

**Why this file exists: three tests were testing the machine, not the code.**

`retrieval._client()` falls back to the real Chroma client when a caller passes none. So a test
that called `index_meeting(mid)` or `delete_meeting("m1")` with no client was asserting one
thing on a developer's laptop and a different thing in CI:

- here, `chromadb` is not installed, `_client()` returns `None`, and "no vector store" is what
  the test observed;
- in CI, `backend/requirements.txt` pins `chromadb>=0.4.0`, so `_client()` returned a real
  store, the deletion actually reached it and correctly reported `index_cleared: True`, and the
  test that demanded `False` failed. The search test failed the same way, with real embeddings
  returning rows where it expected none.

The tests were right about the behaviour and wrong about how they obtained it. Patching each
one would fix those three; this fixture fixes the category, because the next test written the
same way would fail in CI for the same reason and nobody would connect it to this.

**"No store" is the deterministic default here.** Every test that wants a store already says
so — by passing `client=` or by patching `_client` itself — so making the unstated case mean
"none" costs nothing and removes the ambient dependency.

The stub would also happily keep a green suite over a `_client` that had stopped calling
`get_chroma_client` at all, so the real function is handed back through `unstubbed_client` and
the tests that are *about* the fallback call it directly.

**A marker would have read better and would not have worked here.** `pytest_configure` runs
only for the *initial* conftest files. Under `pytest tests/meetingsense` this one is initial
and a marker registers fine; under CI's `pytest -q` from `backend/` it is not, the marker never
registers, and the declaration reads as intentional while behaving like a typo. A fixture is
resolved the same way under both invocations, which is the property that matters for a file
whose entire purpose is that the suite stops depending on how it was started.
"""

from __future__ import annotations

import pytest

import app.meetingsense.retrieval as _retrieval

#: Captured at import, before anything can stub it.
_REAL_CLIENT = _retrieval._client


@pytest.fixture(autouse=True)
def _no_ambient_vector_store(monkeypatch):
    """An unnamed vector store is no vector store, on every machine."""
    monkeypatch.setattr(_retrieval, "_client", lambda client=None: client)


@pytest.fixture()
def unstubbed_client():
    """The real `_client`, for the tests that check the fallback still exists."""
    return _REAL_CLIENT
