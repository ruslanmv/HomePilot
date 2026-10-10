# backend/tests/test_vectordb_client.py
"""
Opening a project reads its knowledge-base document count. That read must be
cheap and must not write: one Chroma client per storage path, and a project
with no knowledge base reports 0 without a collection being created for it.

No ChromaDB needed — the client is a stand-in.
"""
import pytest


class _Collection:
    def __init__(self, n):
        self.n = n

    def count(self):
        return self.n


class _Client:
    def __init__(self, existing=None):
        self.existing = dict(existing or {})
        self.created = []

    def get_collection(self, name):
        if name not in self.existing:
            raise ValueError(f"Collection [{name}] does not exist")
        return _Collection(self.existing[name])

    def get_or_create_collection(self, name, metadata=None):
        self.created.append(name)
        return _Collection(self.existing.setdefault(name, 0))


@pytest.fixture()
def vectordb():
    import app.vectordb as vectordb
    return vectordb


def test_counting_a_project_without_a_knowledge_base_creates_nothing(vectordb, monkeypatch):
    fake = _Client()
    monkeypatch.setattr(vectordb, "get_chroma_client", lambda: fake)
    assert vectordb.get_project_document_count("proj-1") == 0
    assert fake.created == []


def test_counting_reads_the_existing_collection(vectordb, monkeypatch):
    fake = _Client({vectordb.collection_name("proj-1"): 7})
    monkeypatch.setattr(vectordb, "get_chroma_client", lambda: fake)
    assert vectordb.get_project_document_count("proj-1") == 7
    assert fake.created == []


def test_one_client_per_storage_path(vectordb, monkeypatch, tmp_path):
    built = []

    class _Chroma:
        @staticmethod
        def PersistentClient(path, settings=None):
            built.append(path)
            return object()

    monkeypatch.setattr(vectordb, "CHROMADB_AVAILABLE", True)
    monkeypatch.setattr(vectordb, "chromadb", _Chroma)
    monkeypatch.setattr(vectordb, "Settings", lambda **kw: kw)
    monkeypatch.setattr(vectordb, "_clients", {})

    monkeypatch.setattr(vectordb, "CHROMA_DB_PATH", tmp_path / "a")
    first = vectordb.get_chroma_client()
    assert vectordb.get_chroma_client() is first

    # A different path (as a test that relocates the store would use) is its own client.
    monkeypatch.setattr(vectordb, "CHROMA_DB_PATH", tmp_path / "b")
    assert vectordb.get_chroma_client() is not first
    assert built == [str(tmp_path / "a"), str(tmp_path / "b")]


def test_warmup_never_raises(vectordb, monkeypatch):
    def broken():
        raise RuntimeError("store is locked")

    monkeypatch.setattr(vectordb, "CHROMADB_AVAILABLE", True)
    monkeypatch.setattr(vectordb, "get_chroma_client", broken)
    vectordb.warm_chroma_client()
