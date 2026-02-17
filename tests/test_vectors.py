"""Tests for vector storage — pure functions and VectorStore logic."""

import pytest

from src.storage.vectors import (
    ALL_COLLECTIONS,
    COLLECTION_AGENT_TURNS,
    COLLECTION_DOCUMENTS,
    COLLECTION_EMAILS,
    COLLECTION_PROJECTS,
    COLLECTION_RAW,
    VectorStore,
    _clean_metadata,
)


# --- Metadata cleaning ---


class TestCleanMetadata:
    def test_strings_pass_through(self):
        result = _clean_metadata({"key": "value"})
        assert result == {"key": "value"}

    def test_ints_pass_through(self):
        result = _clean_metadata({"count": 42})
        assert result == {"count": 42}

    def test_floats_pass_through(self):
        result = _clean_metadata({"score": 0.95})
        assert result == {"score": 0.95}

    def test_bools_pass_through(self):
        result = _clean_metadata({"active": True})
        assert result == {"active": True}

    def test_none_values_dropped(self):
        result = _clean_metadata({"key": "value", "empty": None})
        assert result == {"key": "value"}
        assert "empty" not in result

    def test_lists_joined(self):
        result = _clean_metadata({"tags": ["python", "async", "web"]})
        assert result == {"tags": "python, async, web"}

    def test_tuples_joined(self):
        result = _clean_metadata({"tags": ("a", "b")})
        assert result == {"tags": "a, b"}

    def test_other_types_stringified(self):
        result = _clean_metadata({"obj": {"nested": True}})
        assert isinstance(result["obj"], str)

    def test_empty_dict(self):
        assert _clean_metadata({}) == {}

    def test_all_none_values(self):
        result = _clean_metadata({"a": None, "b": None})
        assert result == {}

    def test_mixed_types(self):
        result = _clean_metadata({
            "name": "test",
            "count": 5,
            "score": 0.8,
            "active": True,
            "tags": ["a", "b"],
            "empty": None,
        })
        assert result == {
            "name": "test",
            "count": 5,
            "score": 0.8,
            "active": True,
            "tags": "a, b",
        }

    def test_list_with_non_strings(self):
        result = _clean_metadata({"nums": [1, 2, 3]})
        assert result == {"nums": "1, 2, 3"}


# --- Collection constants ---


class TestCollections:
    def test_all_collections_count(self):
        assert len(ALL_COLLECTIONS) == 5

    def test_collection_names(self):
        assert COLLECTION_EMAILS == "emails"
        assert COLLECTION_DOCUMENTS == "documents"
        assert COLLECTION_PROJECTS == "projects"
        assert COLLECTION_RAW == "raw_interactions"
        assert COLLECTION_AGENT_TURNS == "agent_turns"

    def test_all_collections_contains_all(self):
        assert COLLECTION_EMAILS in ALL_COLLECTIONS
        assert COLLECTION_DOCUMENTS in ALL_COLLECTIONS
        assert COLLECTION_PROJECTS in ALL_COLLECTIONS
        assert COLLECTION_RAW in ALL_COLLECTIONS


# --- VectorStore without Chroma (testing init/config) ---


class TestVectorStoreInit:
    def test_default_no_persist(self):
        store = VectorStore()
        assert store._persist_dir is None
        assert store._client is None
        assert store._collections == {}

    def test_with_persist_dir(self):
        store = VectorStore(persist_directory="/tmp/test-chroma")
        assert store._persist_dir == "/tmp/test-chroma"

    def test_add_skips_empty_text(self):
        """add() should silently skip empty text without touching Chroma."""
        store = VectorStore()
        # This should NOT try to init the client
        store.add("emails", "test-id", "", {})
        assert store._client is None  # Still not initialized

    def test_add_skips_whitespace_text(self):
        store = VectorStore()
        store.add("emails", "test-id", "   \n  ", {})
        assert store._client is None

    def test_search_empty_query_returns_empty(self):
        store = VectorStore()
        assert store.search("") == []
        assert store.search("   ") == []
        assert store._client is None  # No client init needed


# --- VectorStore with mock Chroma ---


class _MockCollection:
    """Minimal mock of a Chroma collection."""

    def __init__(self):
        self._docs = {}

    def upsert(self, ids, documents, metadatas):
        for i, doc_id in enumerate(ids):
            self._docs[doc_id] = {
                "document": documents[i],
                "metadata": metadatas[i] if metadatas else {},
            }

    def count(self):
        return len(self._docs)

    def query(self, query_texts, n_results, **kwargs):
        # Return all docs sorted by insertion order
        ids = list(self._docs.keys())[:n_results]
        return {
            "ids": [ids],
            "documents": [[self._docs[i]["document"] for i in ids]],
            "metadatas": [[self._docs[i]["metadata"] for i in ids]],
            "distances": [[0.1 * (j + 1) for j in range(len(ids))]],
        }

    def delete(self, ids):
        for doc_id in ids:
            self._docs.pop(doc_id, None)


class _MockChromaClient:
    def __init__(self):
        self._collections = {}

    def get_or_create_collection(self, name, **kwargs):
        if name not in self._collections:
            self._collections[name] = _MockCollection()
        return self._collections[name]

    def delete_collection(self, name):
        self._collections.pop(name, None)


class TestVectorStoreWithMock:
    def _make_store(self):
        store = VectorStore()
        store._client = _MockChromaClient()
        return store

    def test_add_and_search(self):
        store = self._make_store()
        store.add("emails", "e1", "Hello world email")
        store.add("emails", "e2", "Another email about Python")

        results = store.search("hello", collections=["emails"])
        assert len(results) == 2
        assert results[0]["id"] == "e1"
        assert results[0]["collection"] == "emails"
        assert results[0]["text"] == "Hello world email"

    def test_add_with_metadata(self):
        store = self._make_store()
        store.add("emails", "e1", "Test email", {"classification": "human"})

        results = store.search("test", collections=["emails"])
        assert results[0]["metadata"]["classification"] == "human"

    def test_add_email_helper(self):
        store = self._make_store()
        store.add_email("e1", "Email content")
        assert store.collection_count("emails") == 1

    def test_add_document_helper(self):
        store = self._make_store()
        store.add_document("d1", "Doc content")
        assert store.collection_count("documents") == 1

    def test_add_project_helper(self):
        store = self._make_store()
        store.add_project("p1", "Project content")
        assert store.collection_count("projects") == 1

    def test_add_raw_helper(self):
        store = self._make_store()
        store.add_raw("r1", "Raw interaction")
        assert store.collection_count("raw_interactions") == 1

    def test_search_across_collections(self):
        store = self._make_store()
        store.add_email("e1", "Email about focus")
        store.add_document("d1", "Document about focus")
        store.add_project("p1", "Focus project")

        results = store.search("focus")
        assert len(results) == 3

    def test_search_respects_n_results(self):
        store = self._make_store()
        for i in range(5):
            store.add_email(f"e{i}", f"Email number {i}")

        results = store.search("email", n_results=3)
        assert len(results) == 3

    def test_search_sorted_by_distance(self):
        store = self._make_store()
        store.add_email("e1", "First email")
        store.add_email("e2", "Second email")

        results = store.search("email")
        # Mock returns ascending distances
        assert results[0]["distance"] <= results[1]["distance"]

    def test_delete(self):
        store = self._make_store()
        store.add_email("e1", "Email to delete")
        assert store.collection_count("emails") == 1
        store.delete("emails", "e1")
        assert store.collection_count("emails") == 0

    def test_reset_collection(self):
        store = self._make_store()
        store.add_email("e1", "Email one")
        store.add_email("e2", "Email two")
        assert store.collection_count("emails") == 2
        store.reset_collection("emails")
        # After reset, collection is recreated empty
        assert "emails" not in store._collections

    def test_upsert_updates_existing(self):
        store = self._make_store()
        store.add_email("e1", "Original text")
        store.add_email("e1", "Updated text")
        assert store.collection_count("emails") == 1
        results = store.search("text", collections=["emails"])
        assert results[0]["text"] == "Updated text"

    def test_search_skips_empty_collections(self):
        store = self._make_store()
        # Add to only one collection
        store.add_email("e1", "Test email")
        results = store.search("test")
        # Should only get the email, not crash on empty collections
        assert len(results) == 1

    def test_search_with_specific_collections(self):
        store = self._make_store()
        store.add_email("e1", "Email about test")
        store.add_document("d1", "Doc about test")

        results = store.search("test", collections=["documents"])
        assert len(results) == 1
        assert results[0]["collection"] == "documents"
