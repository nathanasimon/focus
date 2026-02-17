import { useCommitments } from '../hooks/use-focus-data'

export function Commitments() {
  const { data: commitments, isLoading, error } = useCommitments()

  return (
    <section className="mb-10">
      <h2 className="text-2xl font-heading mb-4 text-text-dim">Open Commitments</h2>
      {isLoading && <p className="text-muted text-sm">Loading...</p>}
      {error && <p className="text-red text-sm">Failed to load</p>}
      {!isLoading && commitments?.length === 0 && (
        <p className="text-muted text-sm">No open commitments.</p>
      )}
      {commitments && commitments.length > 0 && (
        <div className="space-y-2">
          {commitments.map((c) => (
            <div
              key={c.id}
              className="flex items-start gap-3 p-3 rounded-lg bg-surface
                         border border-border"
            >
              <span className="text-sm mt-0.5">
                {c.direction === 'to_me' ? (
                  <span className="text-amber" title="Owed to me">&larr;</span>
                ) : (
                  <span className="text-blue" title="I promised">&rarr;</span>
                )}
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-sm truncate">{c.description}</p>
                <div className="flex gap-3 mt-1">
                  {c.person_name && (
                    <span className="text-xs text-muted">
                      {c.direction === 'to_me' ? `From ${c.person_name}` : `To ${c.person_name}`}
                    </span>
                  )}
                  {c.deadline && (
                    <span className="text-xs text-amber">Due {c.deadline}</span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
