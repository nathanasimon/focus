-- Focus Database Schema
-- Run: psql -d focus -f schema.sql

-- People you interact with
CREATE TABLE IF NOT EXISTS people (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    relationship TEXT CHECK (relationship IN
        ('colleague', 'advisor', 'friend', 'family', 'vendor', 'acquaintance', 'unknown')),
    organization TEXT,
    first_contact TIMESTAMPTZ,
    last_contact TIMESTAMPTZ,
    notes TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Email accounts (multi-account support)
CREATE TABLE IF NOT EXISTS email_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    provider TEXT DEFAULT 'gmail',
    priority_weight FLOAT DEFAULT 1.0,
    sync_enabled BOOLEAN DEFAULT TRUE,
    process_newsletters BOOLEAN DEFAULT FALSE,
    oauth_token JSONB,
    sync_cursor TEXT,
    last_sync TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Projects (auto-tiered)
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    tier TEXT CHECK (tier IN ('fleeting', 'simple', 'complex', 'life_thread')) DEFAULT 'simple',
    status TEXT CHECK (status IN ('active', 'paused', 'completed', 'abandoned')) DEFAULT 'active',
    description TEXT,
    first_mention TIMESTAMPTZ,
    last_activity TIMESTAMPTZ,
    mention_count INTEGER DEFAULT 0,
    source_diversity INTEGER DEFAULT 0,
    people_count INTEGER DEFAULT 0,
    user_pinned BOOLEAN DEFAULT FALSE,
    user_priority TEXT CHECK (user_priority IN ('critical', 'high', 'normal', 'low')),
    user_deadline DATE,
    user_deadline_note TEXT,
    auto_archive_after DATE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sprints (time-bounded priority overrides)
CREATE TABLE IF NOT EXISTS sprints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    priority_boost FLOAT DEFAULT 2.0,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    auto_archive_project BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tasks / Kanban items
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT CHECK (status IN ('backlog', 'in_progress', 'waiting', 'done')) DEFAULT 'backlog',
    priority TEXT CHECK (priority IN ('urgent', 'high', 'normal', 'low')) DEFAULT 'normal',
    assigned_to UUID REFERENCES people(id) ON DELETE SET NULL,
    waiting_on UUID REFERENCES people(id) ON DELETE SET NULL,
    waiting_since TIMESTAMPTZ,
    due_date DATE,
    user_pinned BOOLEAN DEFAULT FALSE,
    user_priority TEXT CHECK (user_priority IN ('urgent', 'high', 'normal', 'low')),
    source_type TEXT,
    source_id TEXT,
    source_account_id UUID REFERENCES email_accounts(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Commitments (promises you or others made)
CREATE TABLE IF NOT EXISTS commitments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE SET NULL,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    direction TEXT CHECK (direction IN ('from_me', 'to_me')) NOT NULL,
    description TEXT NOT NULL,
    deadline DATE,
    status TEXT CHECK (status IN ('open', 'fulfilled', 'broken', 'cancelled')) DEFAULT 'open',
    source_type TEXT,
    source_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    fulfilled_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Processed emails
CREATE TABLE IF NOT EXISTS emails (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID REFERENCES email_accounts(id) ON DELETE SET NULL,
    gmail_id TEXT NOT NULL,
    thread_id TEXT,
    sender_id UUID REFERENCES people(id) ON DELETE SET NULL,
    subject TEXT,
    snippet TEXT,
    full_body TEXT,
    classification TEXT CHECK (classification IN
        ('human', 'automated', 'newsletter', 'spam', 'system')),
    urgency TEXT CHECK (urgency IN ('urgent', 'normal', 'low')),
    needs_reply BOOLEAN DEFAULT FALSE,
    reply_suggested TEXT,
    reply_sent BOOLEAN DEFAULT FALSE,
    labels TEXT[],
    processed_at TIMESTAMPTZ,
    email_date TIMESTAMPTZ,
    raw_headers JSONB,
    extraction_result JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(account_id, gmail_id)
);

-- Text messages
CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id TEXT UNIQUE NOT NULL,
    sender_id UUID REFERENCES people(id) ON DELETE SET NULL,
    content TEXT,
    is_from_me BOOLEAN,
    chat_id TEXT,
    message_date TIMESTAMPTZ,
    has_attachment BOOLEAN DEFAULT FALSE,
    extraction_result JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Google Drive documents
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    drive_id TEXT UNIQUE NOT NULL,
    title TEXT,
    mime_type TEXT,
    folder_path TEXT,
    owner_id UUID REFERENCES people(id) ON DELETE SET NULL,
    last_modified TIMESTAMPTZ,
    content_hash TEXT,
    extracted_text TEXT,
    linked_projects UUID[],
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Junction tables
CREATE TABLE IF NOT EXISTS project_people (
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    role TEXT,
    PRIMARY KEY (project_id, person_id)
);

-- Sync state (per source, per account)
CREATE TABLE IF NOT EXISTS sync_state (
    id TEXT PRIMARY KEY,
    account_id UUID REFERENCES email_accounts(id) ON DELETE CASCADE,
    last_sync TIMESTAMPTZ,
    cursor TEXT,
    status TEXT,
    error_message TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Raw interactions — permanent archive
CREATE TABLE IF NOT EXISTS raw_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type TEXT NOT NULL,
    source_id TEXT,
    account_id UUID REFERENCES email_accounts(id) ON DELETE SET NULL,
    raw_content TEXT NOT NULL,
    raw_metadata JSONB DEFAULT '{}',
    content_hash TEXT,
    extraction_version TEXT,
    extraction_model TEXT,
    extraction_result JSONB,
    last_processed_at TIMESTAMPTZ,
    interaction_date TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- AI conversation archive
CREATE TABLE IF NOT EXISTS ai_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_type TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT,
    request_messages JSONB NOT NULL,
    response_content JSONB NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd FLOAT,
    latency_ms INTEGER,
    source_interaction_id UUID REFERENCES raw_interactions(id) ON DELETE SET NULL,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_name TEXT NOT NULL,
    record_id UUID,
    action TEXT CHECK (action IN ('create', 'read', 'update', 'delete')) NOT NULL,
    actor TEXT NOT NULL,
    old_values JSONB,
    new_values JSONB,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- User preferences
CREATE TABLE IF NOT EXISTS user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key TEXT UNIQUE NOT NULL,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================
-- INDEXES
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_people_email ON people(email);
CREATE INDEX IF NOT EXISTS idx_email_accounts_email ON email_accounts(email);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_tier ON projects(tier);
CREATE INDEX IF NOT EXISTS idx_projects_pinned ON projects(user_pinned) WHERE user_pinned = TRUE;
CREATE INDEX IF NOT EXISTS idx_projects_deadline ON projects(user_deadline) WHERE user_deadline IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_tasks_pinned ON tasks(user_pinned) WHERE user_pinned = TRUE;
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_date) WHERE due_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_commitments_status ON commitments(status);
CREATE INDEX IF NOT EXISTS idx_commitments_direction ON commitments(direction);
CREATE INDEX IF NOT EXISTS idx_emails_classification ON emails(classification);
CREATE INDEX IF NOT EXISTS idx_emails_needs_reply ON emails(needs_reply) WHERE needs_reply = TRUE;
CREATE INDEX IF NOT EXISTS idx_emails_thread ON emails(thread_id);
CREATE INDEX IF NOT EXISTS idx_emails_account ON emails(account_id);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(message_date);
CREATE INDEX IF NOT EXISTS idx_documents_folder ON documents(folder_path);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_sprints_active ON sprints(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_sprints_dates ON sprints(starts_at, ends_at);
CREATE INDEX IF NOT EXISTS idx_raw_source ON raw_interactions(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_raw_account ON raw_interactions(account_id);
CREATE INDEX IF NOT EXISTS idx_raw_date ON raw_interactions(interaction_date);
CREATE INDEX IF NOT EXISTS idx_raw_hash ON raw_interactions(content_hash);
CREATE INDEX IF NOT EXISTS idx_raw_extraction_version ON raw_interactions(extraction_version);
CREATE INDEX IF NOT EXISTS idx_ai_conversations_type ON ai_conversations(session_type);
CREATE INDEX IF NOT EXISTS idx_ai_conversations_model ON ai_conversations(model);
CREATE INDEX IF NOT EXISTS idx_ai_conversations_date ON ai_conversations(created_at);

-- =====================================================
-- CONTEXT SYSTEM TABLES
-- =====================================================

-- Agent sessions (one per Claude Code session)
CREATE TABLE IF NOT EXISTS agent_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL UNIQUE,
    transcript_path TEXT,
    workspace_path TEXT,
    provider TEXT DEFAULT 'claude',
    session_title TEXT,
    session_summary TEXT,
    started_at TIMESTAMPTZ,
    last_activity_at TIMESTAMPTZ,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    turn_count INTEGER DEFAULT 0,
    is_processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Individual conversation turns
CREATE TABLE IF NOT EXISTS agent_turns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    turn_number INTEGER NOT NULL,
    user_message TEXT,
    assistant_summary TEXT,
    turn_title TEXT,
    content_hash TEXT NOT NULL,
    model_name TEXT,
    tool_names TEXT[],
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(session_id, turn_number)
);

-- Full raw turn content (separated for query performance)
CREATE TABLE IF NOT EXISTS agent_turn_content (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id UUID NOT NULL REFERENCES agent_turns(id) ON DELETE CASCADE UNIQUE,
    raw_jsonl TEXT NOT NULL,
    assistant_text TEXT,
    content_size INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Entity links from conversation turns
CREATE TABLE IF NOT EXISTS agent_turn_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id UUID NOT NULL REFERENCES agent_turns(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id UUID,
    entity_name TEXT,
    confidence FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Turn artifacts (files, commands, errors extracted from tool calls)
CREATE TABLE IF NOT EXISTS agent_turn_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id UUID NOT NULL REFERENCES agent_turns(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    artifact_value TEXT NOT NULL,
    artifact_metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add new columns to agent_turn_content (safe with IF NOT EXISTS)
DO $$ BEGIN
    ALTER TABLE agent_turn_content ADD COLUMN IF NOT EXISTS files_touched TEXT[];
    ALTER TABLE agent_turn_content ADD COLUMN IF NOT EXISTS commands_run TEXT[];
    ALTER TABLE agent_turn_content ADD COLUMN IF NOT EXISTS errors_encountered TEXT[];
    ALTER TABLE agent_turn_content ADD COLUMN IF NOT EXISTS tool_call_count INTEGER;
EXCEPTION WHEN OTHERS THEN NULL;
END $$;

-- Durable job queue with lease-based locking
CREATE TABLE IF NOT EXISTS focus_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind TEXT NOT NULL,
    dedupe_key TEXT UNIQUE,
    payload JSONB NOT NULL,
    status TEXT DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'retry', 'done', 'failed')),
    priority INTEGER DEFAULT 10,
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 10,
    locked_until TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Context system indexes
CREATE INDEX IF NOT EXISTS idx_agent_sessions_workspace ON agent_sessions(workspace_path);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_project ON agent_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_processed ON agent_sessions(is_processed) WHERE is_processed = FALSE;
CREATE INDEX IF NOT EXISTS idx_agent_sessions_activity ON agent_sessions(last_activity_at);
CREATE INDEX IF NOT EXISTS idx_agent_turns_session ON agent_turns(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_turns_hash ON agent_turns(content_hash);
CREATE INDEX IF NOT EXISTS idx_agent_turns_started ON agent_turns(started_at);
CREATE INDEX IF NOT EXISTS idx_agent_turn_entities_turn ON agent_turn_entities(turn_id);
CREATE INDEX IF NOT EXISTS idx_agent_turn_entities_entity ON agent_turn_entities(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_focus_jobs_claimable ON focus_jobs(priority, created_at) WHERE status IN ('queued', 'retry');
CREATE INDEX IF NOT EXISTS idx_focus_jobs_kind ON focus_jobs(kind);
CREATE INDEX IF NOT EXISTS idx_focus_jobs_locked ON focus_jobs(locked_until) WHERE status = 'processing';
CREATE INDEX IF NOT EXISTS idx_focus_jobs_dedupe ON focus_jobs(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_agent_turn_artifacts_turn ON agent_turn_artifacts(turn_id);
CREATE INDEX IF NOT EXISTS idx_agent_turn_artifacts_type ON agent_turn_artifacts(artifact_type);
