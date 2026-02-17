"""Tests for API response models and endpoint structure."""

from datetime import date, datetime
from uuid import uuid4

from src.api.routes import (
    CommitmentResponse,
    DocumentResponse,
    EmailResponse,
    PersonResponse,
    PriorityItem,
    ProjectResponse,
    SprintResponse,
    SyncResponse,
    TaskResponse,
)


class TestProjectResponse:
    def test_from_dict(self):
        data = {
            "id": uuid4(),
            "name": "Test",
            "slug": "test",
            "tier": "simple",
            "status": "active",
            "description": "A test project",
            "user_pinned": True,
            "user_priority": "high",
            "user_deadline": date(2026, 3, 1),
            "mention_count": 10,
        }
        resp = ProjectResponse(**data)
        assert resp.name == "Test"
        assert resp.user_pinned is True

    def test_optional_fields_default(self):
        data = {
            "id": uuid4(),
            "name": "Test",
            "slug": "test",
            "tier": "simple",
            "status": "active",
        }
        resp = ProjectResponse(**data)
        assert resp.description is None
        assert resp.user_priority is None
        assert resp.mention_count == 0


class TestTaskResponse:
    def test_from_dict(self):
        data = {
            "id": uuid4(),
            "title": "Do stuff",
            "status": "backlog",
            "priority": "normal",
        }
        resp = TaskResponse(**data)
        assert resp.title == "Do stuff"


class TestPersonResponse:
    def test_from_dict(self):
        data = {
            "id": uuid4(),
            "name": "John Doe",
            "email": "john@example.com",
        }
        resp = PersonResponse(**data)
        assert resp.name == "John Doe"


class TestEmailResponse:
    def test_from_dict(self):
        data = {
            "id": uuid4(),
            "subject": "Hello",
            "classification": "human",
            "urgency": "normal",
            "needs_reply": True,
            "email_date": datetime(2026, 2, 1),
        }
        resp = EmailResponse(**data)
        assert resp.needs_reply is True


class TestDocumentResponse:
    def test_from_dict(self):
        data = {
            "id": uuid4(),
            "drive_id": "1abc123",
            "title": "Meeting Notes",
            "mime_type": "application/vnd.google-apps.document",
            "folder_path": "My Drive/Work",
            "last_modified": datetime(2026, 2, 1),
        }
        resp = DocumentResponse(**data)
        assert resp.drive_id == "1abc123"
        assert resp.title == "Meeting Notes"

    def test_optional_fields(self):
        data = {"id": uuid4(), "drive_id": "xyz"}
        resp = DocumentResponse(**data)
        assert resp.title is None
        assert resp.folder_path is None


class TestSyncResponse:
    def test_from_dict(self):
        resp = SyncResponse(accounts=2, emails_fetched=15, drive_files_synced=3, classified=10, deep_extracted=5, regex_parsed=3)
        assert resp.accounts == 2
        assert resp.emails_fetched == 15
        assert resp.drive_files_synced == 3

    def test_drive_default_zero(self):
        resp = SyncResponse(accounts=1, emails_fetched=5)
        assert resp.drive_files_synced == 0


class TestPriorityItem:
    def test_from_dict(self):
        item = PriorityItem(name="Focus", slug="focus", score=142.5, pinned=True, priority="critical", deadline=date(2026, 3, 1))
        assert item.score == 142.5
        assert item.pinned is True

    def test_optional_fields(self):
        item = PriorityItem(name="Side", slug="side", score=5.0, pinned=False)
        assert item.priority is None
        assert item.deadline is None


class TestSearchResult:
    def test_from_dict(self):
        from src.api.routes import SearchResult

        result = SearchResult(
            collection="emails",
            id="e1",
            text="Test email about python",
            metadata={"classification": "human"},
            score=0.85,
        )
        assert result.collection == "emails"
        assert result.score == 0.85

    def test_defaults(self):
        from src.api.routes import SearchResult

        result = SearchResult(collection="projects", id="p1", text="")
        assert result.metadata == {}
        assert result.score == 0.0


class TestCommitmentResponse:
    def test_from_dict(self):
        resp = CommitmentResponse(
            id=uuid4(),
            person_name="Alice",
            direction="to_me",
            description="Send report by Friday",
            deadline=date(2026, 3, 1),
            status="open",
            source_type="email",
            created_at=datetime(2026, 2, 1),
        )
        assert resp.direction == "to_me"
        assert resp.person_name == "Alice"

    def test_optional_fields(self):
        resp = CommitmentResponse(
            id=uuid4(),
            direction="from_me",
            description="Review PR",
            status="open",
        )
        assert resp.person_name is None
        assert resp.deadline is None


class TestSprintResponse:
    def test_from_dict(self):
        resp = SprintResponse(
            id=uuid4(),
            name="Sprint 1",
            description="First sprint",
            project_name="Focus",
            starts_at=datetime(2026, 2, 1),
            ends_at=datetime(2026, 2, 14),
            is_active=True,
        )
        assert resp.name == "Sprint 1"
        assert resp.is_active is True

    def test_optional_fields(self):
        resp = SprintResponse(
            id=uuid4(),
            name="Sprint 2",
            starts_at=datetime(2026, 2, 15),
            ends_at=datetime(2026, 2, 28),
            is_active=False,
        )
        assert resp.project_name is None
        assert resp.description is None


class TestEmailResponseExtended:
    def test_sender_name_field(self):
        resp = EmailResponse(
            id=uuid4(),
            subject="Meeting",
            sender_name="Bob Smith",
            reply_suggested="Sounds good!",
            needs_reply=True,
        )
        assert resp.sender_name == "Bob Smith"
        assert resp.reply_suggested == "Sounds good!"

    def test_sender_name_defaults_none(self):
        resp = EmailResponse(id=uuid4())
        assert resp.sender_name is None
        assert resp.reply_suggested is None


class TestCorsMiddleware:
    def test_cors_configured(self):
        """CORS middleware is present on the app."""
        from src.api.routes import app

        middleware_classes = [type(m).__name__ for m in app.user_middleware]
        # FastAPI stores middleware as Middleware objects with cls attribute
        has_cors = any("CORS" in str(m) for m in app.user_middleware)
        assert has_cors
