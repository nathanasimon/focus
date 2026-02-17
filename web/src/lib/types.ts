export interface Email {
  id: string
  subject: string | null
  classification: string | null
  urgency: string | null
  needs_reply: boolean
  email_date: string | null
  sender_name: string | null
  reply_suggested: string | null
}

export interface Task {
  id: string
  title: string
  status: string
  priority: string
  project_id: string | null
  due_date: string | null
  user_pinned: boolean
  user_priority: string | null
}

export interface Commitment {
  id: string
  person_name: string | null
  direction: string
  description: string
  deadline: string | null
  status: string
  source_type: string | null
  created_at: string | null
}

export interface Sprint {
  id: string
  name: string
  description: string | null
  project_name: string | null
  starts_at: string
  ends_at: string
  is_active: boolean
}

export interface SyncResponse {
  accounts: number
  emails_fetched: number
  drive_files_synced: number
  classified: number
  deep_extracted: number
  regex_parsed: number
}

export interface SearchResult {
  collection: string
  id: string
  text: string
  metadata: Record<string, unknown>
  score: number
}
