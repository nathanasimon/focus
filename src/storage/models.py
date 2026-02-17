"""SQLAlchemy ORM models for Focus."""

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Person(Base):
    __tablename__ = "people"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(Text)
    relationship_type: Mapped[Optional[str]] = mapped_column(
        "relationship",
        String,
        CheckConstraint(
            "relationship IN ('colleague','advisor','friend','family','vendor','acquaintance','unknown')"
        ),
    )
    organization: Mapped[Optional[str]] = mapped_column(Text)
    first_contact: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_contact: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_people_email", "email"),
    )


class EmailAccount(Base):
    __tablename__ = "email_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(Text, default="gmail")
    priority_weight: Mapped[float] = mapped_column(Float, default=1.0)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    process_newsletters: Mapped[bool] = mapped_column(Boolean, default=False)
    oauth_token: Mapped[Optional[dict]] = mapped_column(JSONB)
    sync_cursor: Mapped[Optional[str]] = mapped_column(Text)
    last_sync: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    tier: Mapped[str] = mapped_column(
        String,
        CheckConstraint("tier IN ('fleeting','simple','complex','life_thread')"),
        default="simple",
    )
    status: Mapped[str] = mapped_column(
        String,
        CheckConstraint("status IN ('active','paused','completed','abandoned')"),
        default="active",
    )
    description: Mapped[Optional[str]] = mapped_column(Text)
    first_mention: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_activity: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    source_diversity: Mapped[int] = mapped_column(Integer, default=0)
    people_count: Mapped[int] = mapped_column(Integer, default=0)
    user_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    user_priority: Mapped[Optional[str]] = mapped_column(
        String,
        CheckConstraint("user_priority IN ('critical','high','normal','low') OR user_priority IS NULL"),
    )
    user_deadline: Mapped[Optional[date]] = mapped_column(Date)
    user_deadline_note: Mapped[Optional[str]] = mapped_column(Text)
    auto_archive_after: Mapped[Optional[date]] = mapped_column(Date)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    tasks: Mapped[list["Task"]] = relationship(back_populates="project")
    sprints: Mapped[list["Sprint"]] = relationship(back_populates="project")

    __table_args__ = (
        Index("idx_projects_status", "status"),
        Index("idx_projects_tier", "tier"),
        Index("idx_projects_pinned", "user_pinned", postgresql_where="user_pinned = TRUE"),
        Index("idx_projects_deadline", "user_deadline", postgresql_where="user_deadline IS NOT NULL"),
    )


class Sprint(Base):
    __tablename__ = "sprints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    priority_boost: Mapped[float] = mapped_column(Float, default=2.0)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_archive_project: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Optional["Project"]] = relationship(back_populates="sprints")

    __table_args__ = (
        Index("idx_sprints_active", "is_active", postgresql_where="is_active = TRUE"),
        Index("idx_sprints_dates", "starts_at", "ends_at"),
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String,
        CheckConstraint("status IN ('backlog','in_progress','waiting','done')"),
        default="backlog",
    )
    priority: Mapped[str] = mapped_column(
        String,
        CheckConstraint("priority IN ('urgent','high','normal','low')"),
        default="normal",
    )
    assigned_to: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id", ondelete="SET NULL")
    )
    waiting_on: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id", ondelete="SET NULL")
    )
    waiting_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    user_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    user_priority: Mapped[Optional[str]] = mapped_column(
        String,
        CheckConstraint("user_priority IN ('urgent','high','normal','low') OR user_priority IS NULL"),
    )
    source_type: Mapped[Optional[str]] = mapped_column(Text)
    source_id: Mapped[Optional[str]] = mapped_column(Text)
    source_account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_accounts.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped[Optional["Project"]] = relationship(back_populates="tasks")

    __table_args__ = (
        Index("idx_tasks_status", "status"),
        Index("idx_tasks_project", "project_id"),
        Index("idx_tasks_assigned", "assigned_to"),
        Index("idx_tasks_pinned", "user_pinned", postgresql_where="user_pinned = TRUE"),
        Index("idx_tasks_due", "due_date", postgresql_where="due_date IS NOT NULL"),
    )


class Commitment(Base):
    __tablename__ = "commitments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id", ondelete="SET NULL")
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    direction: Mapped[str] = mapped_column(
        String,
        CheckConstraint("direction IN ('from_me','to_me')"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    deadline: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String,
        CheckConstraint("status IN ('open','fulfilled','broken','cancelled')"),
        default="open",
    )
    source_type: Mapped[Optional[str]] = mapped_column(Text)
    source_id: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fulfilled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    person: Mapped[Optional["Person"]] = relationship()

    __table_args__ = (
        Index("idx_commitments_status", "status"),
        Index("idx_commitments_direction", "direction"),
    )


class Email(Base):
    __tablename__ = "emails"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_accounts.id", ondelete="SET NULL")
    )
    gmail_id: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[Optional[str]] = mapped_column(Text)
    sender_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id", ondelete="SET NULL")
    )
    subject: Mapped[Optional[str]] = mapped_column(Text)
    snippet: Mapped[Optional[str]] = mapped_column(Text)
    full_body: Mapped[Optional[str]] = mapped_column(Text)
    classification: Mapped[Optional[str]] = mapped_column(
        String,
        CheckConstraint("classification IN ('human','automated','newsletter','spam','system')"),
    )
    urgency: Mapped[Optional[str]] = mapped_column(
        String,
        CheckConstraint("urgency IN ('urgent','normal','low')"),
    )
    needs_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    reply_suggested: Mapped[Optional[str]] = mapped_column(Text)
    reply_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    labels: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    email_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    raw_headers: Mapped[Optional[dict]] = mapped_column(JSONB)
    extraction_result: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sender: Mapped[Optional["Person"]] = relationship()
    account: Mapped[Optional["EmailAccount"]] = relationship()

    __table_args__ = (
        UniqueConstraint("account_id", "gmail_id"),
        Index("idx_emails_classification", "classification"),
        Index("idx_emails_needs_reply", "needs_reply", postgresql_where="needs_reply = TRUE"),
        Index("idx_emails_thread", "thread_id"),
        Index("idx_emails_account", "account_id"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    sender_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id", ondelete="SET NULL")
    )
    content: Mapped[Optional[str]] = mapped_column(Text)
    is_from_me: Mapped[Optional[bool]] = mapped_column(Boolean)
    chat_id: Mapped[Optional[str]] = mapped_column(Text)
    message_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    has_attachment: Mapped[bool] = mapped_column(Boolean, default=False)
    extraction_result: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_messages_chat", "chat_id"),
        Index("idx_messages_date", "message_date"),
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    drive_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)
    mime_type: Mapped[Optional[str]] = mapped_column(Text)
    folder_path: Mapped[Optional[str]] = mapped_column(Text)
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id", ondelete="SET NULL")
    )
    last_modified: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[Optional[str]] = mapped_column(Text)
    extracted_text: Mapped[Optional[str]] = mapped_column(Text)
    linked_projects: Mapped[Optional[list[uuid.UUID]]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_documents_folder", "folder_path"),
    )


class ProjectPeople(Base):
    __tablename__ = "project_people"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[Optional[str]] = mapped_column(Text)


class SyncState(Base):
    __tablename__ = "sync_state"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_accounts.id", ondelete="CASCADE")
    )
    last_sync: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cursor: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(Text)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RawInteraction(Base):
    __tablename__ = "raw_interactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(Text)
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_accounts.id", ondelete="SET NULL")
    )
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    raw_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, default={})
    content_hash: Mapped[Optional[str]] = mapped_column(Text)
    extraction_version: Mapped[Optional[str]] = mapped_column(Text)
    extraction_model: Mapped[Optional[str]] = mapped_column(Text)
    extraction_result: Mapped[Optional[dict]] = mapped_column(JSONB)
    last_processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    interaction_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_raw_source", "source_type", "source_id"),
        Index("idx_raw_account", "account_id"),
        Index("idx_raw_date", "interaction_date"),
        Index("idx_raw_hash", "content_hash"),
        Index("idx_raw_extraction_version", "extraction_version"),
    )


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_type: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[Optional[str]] = mapped_column(Text)
    request_messages: Mapped[dict] = mapped_column(JSONB, nullable=False)
    response_content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    source_interaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_interactions.id", ondelete="SET NULL")
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_ai_conversations_type", "session_type"),
        Index("idx_ai_conversations_model", "model"),
        Index("idx_ai_conversations_date", "created_at"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    record_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(
        String,
        CheckConstraint("action IN ('create','read','update','delete')"),
        nullable=False,
    )
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    old_values: Mapped[Optional[dict]] = mapped_column(JSONB)
    new_values: Mapped[Optional[dict]] = mapped_column(JSONB)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_audit_timestamp", "timestamp"),
    )


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# =====================================================
# Context System Models
# =====================================================


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    transcript_path: Mapped[Optional[str]] = mapped_column(Text)
    workspace_path: Mapped[Optional[str]] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text, default="claude")
    session_title: Mapped[Optional[str]] = mapped_column(Text)
    session_summary: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    turns: Mapped[list["AgentTurn"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    project: Mapped[Optional["Project"]] = relationship()

    __table_args__ = (
        Index("idx_agent_sessions_workspace", "workspace_path"),
        Index("idx_agent_sessions_project", "project_id"),
        Index("idx_agent_sessions_processed", "is_processed", postgresql_where="is_processed = FALSE"),
        Index("idx_agent_sessions_activity", "last_activity_at"),
    )


class AgentTurn(Base):
    __tablename__ = "agent_turns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False
    )
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    user_message: Mapped[Optional[str]] = mapped_column(Text)
    assistant_summary: Mapped[Optional[str]] = mapped_column(Text)
    turn_title: Mapped[Optional[str]] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[Optional[str]] = mapped_column(Text)
    tool_names: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AgentSession"] = relationship(back_populates="turns")
    content: Mapped[Optional["AgentTurnContent"]] = relationship(
        back_populates="turn", uselist=False, cascade="all, delete-orphan"
    )
    entities: Mapped[list["AgentTurnEntity"]] = relationship(
        back_populates="turn", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["AgentTurnArtifact"]] = relationship(
        back_populates="turn", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("session_id", "turn_number"),
        Index("idx_agent_turns_session", "session_id"),
        Index("idx_agent_turns_hash", "content_hash"),
        Index("idx_agent_turns_started", "started_at"),
    )


class AgentTurnContent(Base):
    __tablename__ = "agent_turn_content"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    turn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_turns.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    raw_jsonl: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_text: Mapped[Optional[str]] = mapped_column(Text)
    content_size: Mapped[Optional[int]] = mapped_column(Integer)
    files_touched: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))
    commands_run: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))
    errors_encountered: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))
    tool_call_count: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    turn: Mapped["AgentTurn"] = relationship(back_populates="content")


class AgentTurnEntity(Base):
    __tablename__ = "agent_turn_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    turn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_turns.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    entity_name: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    turn: Mapped["AgentTurn"] = relationship(back_populates="entities")

    __table_args__ = (
        Index("idx_agent_turn_entities_turn", "turn_id"),
        Index("idx_agent_turn_entities_entity", "entity_type", "entity_id"),
    )


class AgentTurnArtifact(Base):
    __tablename__ = "agent_turn_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    turn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_turns.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_value: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    turn: Mapped["AgentTurn"] = relationship(back_populates="artifacts")

    __table_args__ = (
        Index("idx_agent_turn_artifacts_turn", "turn_id"),
        Index("idx_agent_turn_artifacts_type", "artifact_type"),
    )


class FocusJob(Base):
    __tablename__ = "focus_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String,
        CheckConstraint("status IN ('queued', 'processing', 'retry', 'done', 'failed')"),
        default="queued",
    )
    priority: Mapped[int] = mapped_column(Integer, default=10)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=10)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_focus_jobs_claimable", "priority", "created_at",
              postgresql_where="status IN ('queued', 'retry')"),
        Index("idx_focus_jobs_kind", "kind"),
        Index("idx_focus_jobs_locked", "locked_until",
              postgresql_where="status = 'processing'"),
    )
