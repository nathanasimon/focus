"""Vector storage using Chroma for semantic search."""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Collection names matching the spec
COLLECTION_EMAILS = "emails"
COLLECTION_DOCUMENTS = "documents"
COLLECTION_PROJECTS = "projects"
COLLECTION_RAW = "raw_interactions"
COLLECTION_AGENT_TURNS = "agent_turns"

ALL_COLLECTIONS = [COLLECTION_EMAILS, COLLECTION_DOCUMENTS, COLLECTION_PROJECTS, COLLECTION_RAW, COLLECTION_AGENT_TURNS]


class VectorStore:
    """Chroma-backed vector store for semantic search.

    Lazily initializes the Chroma client so the module can be imported
    without chromadb installed.
    """

    def __init__(self, persist_directory: Optional[str] = None):
        self._persist_dir = persist_directory
        self._client = None
        self._collections: dict = {}

    def _get_client(self):
        """Lazily initialize the Chroma persistent client."""
        if self._client is None:
            import chromadb

            if self._persist_dir:
                Path(self._persist_dir).mkdir(parents=True, exist_ok=True)
                self._client = chromadb.PersistentClient(path=self._persist_dir)
            else:
                self._client = chromadb.Client()
        return self._client

    def _get_collection(self, name: str):
        """Get or create a named collection."""
        if name not in self._collections:
            client = self._get_client()
            self._collections[name] = client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collections[name]

    def add(
        self,
        collection_name: str,
        doc_id: str,
        text: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Add or update a document in a collection.

        Args:
            collection_name: Which collection (emails, documents, projects, raw_interactions).
            doc_id: Unique ID string for this document.
            text: The text content to embed.
            metadata: Optional metadata dict for filtering.
        """
        if not text or not text.strip():
            return

        collection = self._get_collection(collection_name)

        # Clean metadata: Chroma only accepts str/int/float/bool values
        clean_meta = _clean_metadata(metadata) if metadata else {}

        collection.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[clean_meta],
        )

    def add_email(self, email_id: str, text: str, metadata: Optional[dict] = None) -> None:
        """Add an email to the emails collection."""
        self.add(COLLECTION_EMAILS, email_id, text, metadata)

    def add_document(self, doc_id: str, text: str, metadata: Optional[dict] = None) -> None:
        """Add a Drive document to the documents collection."""
        self.add(COLLECTION_DOCUMENTS, doc_id, text, metadata)

    def add_project(self, project_id: str, text: str, metadata: Optional[dict] = None) -> None:
        """Add a project to the projects collection."""
        self.add(COLLECTION_PROJECTS, project_id, text, metadata)

    def add_raw(self, interaction_id: str, text: str, metadata: Optional[dict] = None) -> None:
        """Add a raw interaction to the raw_interactions collection."""
        self.add(COLLECTION_RAW, interaction_id, text, metadata)

    def add_agent_turn(self, turn_id: str, text: str, metadata: Optional[dict] = None) -> None:
        """Add an agent conversation turn to the agent_turns collection."""
        self.add(COLLECTION_AGENT_TURNS, turn_id, text, metadata)

    def search(
        self,
        query: str,
        collections: Optional[list[str]] = None,
        n_results: int = 10,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """Search across one or more collections.

        Args:
            query: Natural language search query.
            collections: List of collection names to search. None = all.
            n_results: Max results per collection.
            where: Optional Chroma where filter for metadata.

        Returns:
            Sorted list of result dicts with keys:
            collection, id, text, metadata, distance
        """
        if not query or not query.strip():
            return []

        target_collections = collections or ALL_COLLECTIONS
        all_results = []

        for col_name in target_collections:
            try:
                collection = self._get_collection(col_name)

                # Skip empty collections
                if collection.count() == 0:
                    continue

                kwargs = {
                    "query_texts": [query],
                    "n_results": min(n_results, collection.count()),
                }
                if where:
                    kwargs["where"] = where

                results = collection.query(**kwargs)

                # Unpack Chroma's nested result format
                ids = results.get("ids", [[]])[0]
                documents = results.get("documents", [[]])[0]
                metadatas = results.get("metadatas", [[]])[0]
                distances = results.get("distances", [[]])[0]

                for i, doc_id in enumerate(ids):
                    all_results.append({
                        "collection": col_name,
                        "id": doc_id,
                        "text": documents[i] if i < len(documents) else "",
                        "metadata": metadatas[i] if i < len(metadatas) else {},
                        "distance": distances[i] if i < len(distances) else 1.0,
                    })

            except Exception as e:
                logger.warning("Search failed for collection %s: %s", col_name, e)

        # Sort by distance (lower = better match for cosine)
        all_results.sort(key=lambda x: x["distance"])
        return all_results[:n_results]

    def delete(self, collection_name: str, doc_id: str) -> None:
        """Remove a document from a collection."""
        collection = self._get_collection(collection_name)
        collection.delete(ids=[doc_id])

    def collection_count(self, collection_name: str) -> int:
        """Get the number of documents in a collection."""
        return self._get_collection(collection_name).count()

    def reset_collection(self, collection_name: str) -> None:
        """Delete and recreate a collection."""
        client = self._get_client()
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass
        self._collections.pop(collection_name, None)


def _clean_metadata(metadata: dict) -> dict:
    """Clean metadata for Chroma compatibility.

    Chroma only accepts str, int, float, bool values.
    Converts or drops incompatible types.
    """
    clean = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            clean[key] = value
        elif isinstance(value, (list, tuple)):
            # Join lists as comma-separated strings
            clean[key] = ", ".join(str(v) for v in value)
        else:
            clean[key] = str(value)
    return clean


# Module-level singleton
_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """Get or create the global VectorStore instance."""
    global _store
    if _store is None:
        from src.config import get_settings

        settings = get_settings()
        persist_dir = str(settings.general.chroma_path)
        _store = VectorStore(persist_directory=persist_dir)
    return _store


async def index_email(email_id: str, subject: str, body: str, metadata: Optional[dict] = None) -> None:
    """Index an email for semantic search."""
    text = f"{subject or ''}\n{body or ''}".strip()
    if text:
        get_vector_store().add_email(str(email_id), text, metadata)


async def index_document(drive_id: str, title: str, content: str, metadata: Optional[dict] = None) -> None:
    """Index a Drive document for semantic search."""
    text = f"{title or ''}\n{content or ''}".strip()
    if text:
        get_vector_store().add_document(drive_id, text, metadata)


async def index_project(project_id: str, name: str, description: str, metadata: Optional[dict] = None) -> None:
    """Index a project for semantic search."""
    text = f"{name}\n{description or ''}".strip()
    if text:
        get_vector_store().add_project(str(project_id), text, metadata)


async def semantic_search(query: str, collections: Optional[list[str]] = None, n_results: int = 10) -> list[dict]:
    """Run a semantic search across collections."""
    return get_vector_store().search(query, collections=collections, n_results=n_results)


async def reindex_all(session) -> dict:
    """Rebuild all vector indexes from the database.

    Returns counts of items indexed per collection.
    """
    from sqlalchemy import select

    from src.storage.models import Document, Email, Project, RawInteraction

    store = get_vector_store()
    counts = {c: 0 for c in ALL_COLLECTIONS}

    # Reset all collections
    for col in ALL_COLLECTIONS:
        store.reset_collection(col)

    # Index emails
    result = await session.execute(
        select(Email).where(Email.full_body.isnot(None))
    )
    for email in result.scalars():
        text = f"{email.subject or ''}\n{email.full_body or ''}".strip()
        if text:
            meta = {
                "classification": email.classification or "unknown",
                "needs_reply": email.needs_reply,
            }
            if email.email_date:
                meta["date"] = email.email_date.isoformat()
            store.add_email(str(email.id), text, meta)
            counts[COLLECTION_EMAILS] += 1

    # Index documents
    result = await session.execute(
        select(Document).where(Document.extracted_text.isnot(None))
    )
    for doc in result.scalars():
        text = f"{doc.title or ''}\n{doc.extracted_text or ''}".strip()
        if text:
            meta = {"mime_type": doc.mime_type or "", "folder": doc.folder_path or ""}
            if doc.last_modified:
                meta["date"] = doc.last_modified.isoformat()
            store.add_document(doc.drive_id, text, meta)
            counts[COLLECTION_DOCUMENTS] += 1

    # Index projects
    result = await session.execute(
        select(Project).where(Project.status == "active")
    )
    for project in result.scalars():
        text = f"{project.name}\n{project.description or ''}".strip()
        meta = {"tier": project.tier, "status": project.status, "slug": project.slug}
        store.add_project(str(project.id), text, meta)
        counts[COLLECTION_PROJECTS] += 1

    # Index raw interactions (most recent 5000 to avoid huge index)
    result = await session.execute(
        select(RawInteraction)
        .where(RawInteraction.raw_content.isnot(None))
        .order_by(RawInteraction.interaction_date.desc().nullslast())
        .limit(5000)
    )
    for raw in result.scalars():
        text = raw.raw_content[:2000]  # Truncate to keep embeddings focused
        meta = {"source_type": raw.source_type}
        if raw.interaction_date:
            meta["date"] = raw.interaction_date.isoformat()
        store.add_raw(str(raw.id), text, meta)
        counts[COLLECTION_RAW] += 1

    # Index agent turns
    from src.storage.models import AgentTurn

    result = await session.execute(
        select(AgentTurn)
        .where(AgentTurn.user_message.isnot(None))
        .order_by(AgentTurn.started_at.desc().nulls_last())
        .limit(5000)
    )
    for turn in result.scalars():
        text = f"{turn.user_message or ''}\n{turn.assistant_summary or ''}".strip()
        if text:
            meta = {"turn_number": turn.turn_number}
            if turn.started_at:
                meta["date"] = turn.started_at.isoformat()
            store.add_agent_turn(str(turn.id), text[:2000], meta)
            counts[COLLECTION_AGENT_TURNS] += 1

    logger.info(
        "Reindexed vectors: %d emails, %d docs, %d projects, %d raw, %d turns",
        counts[COLLECTION_EMAILS],
        counts[COLLECTION_DOCUMENTS],
        counts[COLLECTION_PROJECTS],
        counts[COLLECTION_RAW],
        counts[COLLECTION_AGENT_TURNS],
    )
    return counts
