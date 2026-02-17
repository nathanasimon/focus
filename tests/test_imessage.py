"""Tests for src/ingestion/imessage — iMessage ingestion."""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ingestion.imessage import (
    APPLE_EPOCH,
    apple_time_to_datetime,
    datetime_to_apple_time,
    is_macos,
    read_messages,
    resolve_message_sender,
    sync_imessages,
)


class TestAppleTimeConversions:
    def test_epoch_start(self):
        """Timestamp 0 should map to Apple epoch (2001-01-01)."""
        result = apple_time_to_datetime(0)
        assert result.year == 2001
        assert result.month == 1
        assert result.day == 1

    def test_nanosecond_timestamp(self):
        """Modern iMessage timestamps (>1 trillion) are nanoseconds."""
        # 1 trillion nanoseconds = 1000 seconds after epoch
        result = apple_time_to_datetime(1_000_000_000_000)
        assert result.year == 2001
        assert result.month == 1
        assert result.day == 1

    def test_second_timestamp(self):
        """Older iMessage timestamps are in seconds."""
        # 86400 seconds = 1 day after epoch
        result = apple_time_to_datetime(86400)
        assert result.year == 2001
        assert result.month == 1
        assert result.day == 2

    def test_roundtrip(self):
        """datetime_to_apple_time and apple_time_to_datetime should roundtrip."""
        dt = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
        apple_ts = datetime_to_apple_time(dt)
        result = apple_time_to_datetime(apple_ts)
        # Allow 1-second tolerance due to float precision
        assert abs((result - dt).total_seconds()) < 1

    def test_none_timestamp(self):
        """None timestamp returns current time."""
        result = apple_time_to_datetime(None)
        assert isinstance(result, datetime)


class TestReadMessages:
    def test_missing_db_returns_empty(self, tmp_path: Path):
        """If the database doesn't exist, return empty list."""
        result = read_messages(db_path=tmp_path / "nonexistent.db")
        assert result == []

    def test_reads_from_sqlite(self, tmp_path: Path):
        """Read messages from a real SQLite database with iMessage schema."""
        db_path = tmp_path / "chat.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE handle (
                ROWID INTEGER PRIMARY KEY,
                id TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE chat (
                ROWID INTEGER PRIMARY KEY,
                chat_identifier TEXT,
                display_name TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE message (
                ROWID INTEGER PRIMARY KEY,
                guid TEXT,
                text TEXT,
                is_from_me INTEGER,
                date INTEGER,
                handle_id INTEGER,
                cache_has_attachments INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE chat_message_join (
                chat_id INTEGER,
                message_id INTEGER
            )
        """)

        # Insert test data
        conn.execute("INSERT INTO handle VALUES (1, '+15551234567')")
        conn.execute("INSERT INTO chat VALUES (1, 'iMessage;+1;+15551234567', 'Test Chat')")

        # Use a nanosecond timestamp (modern format)
        ts = datetime_to_apple_time(datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc))
        conn.execute(
            "INSERT INTO message VALUES (1, 'guid-001', 'Hello there', 0, ?, 1, 0)",
            (ts,),
        )
        conn.execute("INSERT INTO chat_message_join VALUES (1, 1)")
        conn.commit()
        conn.close()

        messages = read_messages(db_path=db_path)
        assert len(messages) == 1
        assert messages[0]["guid"] == "guid-001"
        assert messages[0]["text"] == "Hello there"
        assert messages[0]["is_from_me"] is False
        assert messages[0]["handle_id"] == "+15551234567"
        assert messages[0]["chat_id"] == "iMessage;+1;+15551234567"

    def test_filters_by_since(self, tmp_path: Path):
        """Messages before `since` are excluded."""
        db_path = tmp_path / "chat.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
        conn.execute("CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT, display_name TEXT)")
        conn.execute("""
            CREATE TABLE message (
                ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, is_from_me INTEGER,
                date INTEGER, handle_id INTEGER, cache_has_attachments INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER)")

        conn.execute("INSERT INTO handle VALUES (1, '+15551234567')")
        conn.execute("INSERT INTO chat VALUES (1, 'chat1', 'Chat')")

        old_ts = datetime_to_apple_time(datetime(2025, 1, 1, tzinfo=timezone.utc))
        new_ts = datetime_to_apple_time(datetime(2026, 2, 1, tzinfo=timezone.utc))

        conn.execute("INSERT INTO message VALUES (1, 'old', 'Old msg', 0, ?, 1, 0)", (old_ts,))
        conn.execute("INSERT INTO message VALUES (2, 'new', 'New msg', 0, ?, 1, 0)", (new_ts,))
        conn.execute("INSERT INTO chat_message_join VALUES (1, 1)")
        conn.execute("INSERT INTO chat_message_join VALUES (1, 2)")
        conn.commit()
        conn.close()

        messages = read_messages(
            db_path=db_path,
            since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert len(messages) == 1
        assert messages[0]["guid"] == "new"

    def test_null_text_excluded(self, tmp_path: Path):
        """Messages with NULL text are filtered out by the query."""
        db_path = tmp_path / "chat.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
        conn.execute("CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT, display_name TEXT)")
        conn.execute("""
            CREATE TABLE message (
                ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, is_from_me INTEGER,
                date INTEGER, handle_id INTEGER, cache_has_attachments INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER)")

        ts = datetime_to_apple_time(datetime(2026, 2, 1, tzinfo=timezone.utc))
        conn.execute("INSERT INTO message VALUES (1, 'g1', NULL, 0, ?, 0, 0)", (ts,))
        conn.execute("INSERT INTO message VALUES (2, 'g2', '', 0, ?, 0, 0)", (ts,))
        conn.execute("INSERT INTO message VALUES (3, 'g3', 'Has text', 0, ?, 0, 0)", (ts,))
        conn.commit()
        conn.close()

        messages = read_messages(db_path=db_path)
        assert len(messages) == 1
        assert messages[0]["guid"] == "g3"


class TestResolveMessageSender:
    @pytest.mark.asyncio
    async def test_none_handle(self):
        """None handle returns None."""
        session = AsyncMock()
        result = await resolve_message_sender(session, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_matches_by_phone(self):
        """Matches a person by phone number."""
        person = MagicMock()
        person.id = uuid.uuid4()
        person.name = "Alice"

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = person

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        result = await resolve_message_sender(session, "+15551234567")
        assert result.name == "Alice"

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        """No phone or email match returns None."""
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        result = await resolve_message_sender(session, "+15559999999")
        assert result is None


class TestSyncImessages:
    @pytest.mark.asyncio
    async def test_skips_non_macos(self):
        """On non-macOS, returns immediately."""
        session = AsyncMock()
        with patch("src.ingestion.imessage.is_macos", return_value=False):
            summary = await sync_imessages(session)
        assert summary["messages_read"] == 0
        assert summary["messages_stored"] == 0

    @pytest.mark.asyncio
    async def test_stores_new_messages(self, tmp_path: Path):
        """New messages are stored in the database."""
        db_path = tmp_path / "chat.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
        conn.execute("CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT, display_name TEXT)")
        conn.execute("""
            CREATE TABLE message (
                ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, is_from_me INTEGER,
                date INTEGER, handle_id INTEGER, cache_has_attachments INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER)")
        conn.execute("INSERT INTO handle VALUES (1, '+15551234567')")
        conn.execute("INSERT INTO chat VALUES (1, 'chat1', 'Chat')")

        ts = datetime_to_apple_time(datetime(2026, 2, 1, tzinfo=timezone.utc))
        conn.execute("INSERT INTO message VALUES (1, 'guid-001', 'Test msg', 0, ?, 1, 0)", (ts,))
        conn.execute("INSERT INTO chat_message_join VALUES (1, 1)")
        conn.commit()
        conn.close()

        # Mock the session: no existing message found
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None

        sender_result = MagicMock()
        sender_result.scalar_one_or_none.return_value = None

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[existing_result, sender_result, sender_result])
        session.add = MagicMock()
        session.flush = AsyncMock()

        with patch("src.ingestion.imessage.is_macos", return_value=True), \
             patch("src.ingestion.imessage.store_raw_interaction", new_callable=AsyncMock):
            summary = await sync_imessages(session, db_path=db_path)

        assert summary["messages_read"] == 1
        assert summary["messages_stored"] == 1
        assert summary["errors"] == 0

    @pytest.mark.asyncio
    async def test_skips_duplicate_messages(self, tmp_path: Path):
        """Messages already in the DB are skipped."""
        db_path = tmp_path / "chat.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
        conn.execute("CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT, display_name TEXT)")
        conn.execute("""
            CREATE TABLE message (
                ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, is_from_me INTEGER,
                date INTEGER, handle_id INTEGER, cache_has_attachments INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER)")

        ts = datetime_to_apple_time(datetime(2026, 2, 1, tzinfo=timezone.utc))
        conn.execute("INSERT INTO message VALUES (1, 'guid-dup', 'Dup msg', 0, ?, 0, 0)", (ts,))
        conn.commit()
        conn.close()

        # Mock the session: message already exists
        existing_msg = MagicMock()
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = existing_msg

        session = AsyncMock()
        session.execute = AsyncMock(return_value=existing_result)
        session.flush = AsyncMock()

        with patch("src.ingestion.imessage.is_macos", return_value=True):
            summary = await sync_imessages(session, db_path=db_path)

        assert summary["messages_read"] == 1
        assert summary["messages_stored"] == 0
