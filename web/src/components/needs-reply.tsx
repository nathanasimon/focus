import { useNeedsReply } from '../hooks/use-focus-data'

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return ''
  const diff = Date.now() - new Date(dateStr).getTime()
  const hours = Math.floor(diff / 3_600_000)
  if (hours < 1) return 'just now'
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days === 1) return '1 day ago'
  if (days < 7) return `${days} days ago`
  const weeks = Math.floor(days / 7)
  return weeks === 1 ? '1 week ago' : `${weeks} weeks ago`
}

function urgencyColor(urgency: string | null): string {
  if (urgency === 'urgent') return 'text-red'
  if (urgency === 'normal') return 'text-amber'
  return 'text-text-dim'
}

export function NeedsReply() {
  const { data: emails, isLoading, error } = useNeedsReply()

  return (
    <section className="mb-10">
      <h2 className="text-2xl font-heading mb-4 text-text-dim">Needs Reply</h2>
      {isLoading && <p className="text-muted text-sm">Loading...</p>}
      {error && <p className="text-red text-sm">Failed to load</p>}
      {emails && emails.length === 0 && (
        <p className="text-muted text-sm">All caught up.</p>
      )}
      {emails && emails.length > 0 && (
        <div className="space-y-2">
          {emails.map((email) => (
            <div
              key={email.id}
              className="flex items-start gap-4 p-4 rounded-lg bg-surface
                         border border-border hover:border-amber-dim/50 transition-colors"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-text truncate">
                    {email.sender_name || 'Unknown'}
                  </span>
                  <span className={`text-xs ${urgencyColor(email.urgency)}`}>
                    {timeAgo(email.email_date)}
                  </span>
                </div>
                <p className="text-sm text-text-dim truncate">
                  {email.subject || '(no subject)'}
                </p>
                {email.reply_suggested && (
                  <p className="text-xs text-muted mt-1.5 italic">
                    Suggested: "{email.reply_suggested}"
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
