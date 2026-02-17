import { useActiveTasks } from '../hooks/use-focus-data'

function priorityBadge(priority: string): string {
  switch (priority) {
    case 'urgent': return 'bg-red/20 text-red'
    case 'high': return 'bg-amber/20 text-amber'
    case 'normal': return 'bg-surface text-text-dim'
    case 'low': return 'bg-surface text-muted'
    default: return 'bg-surface text-muted'
  }
}

function statusIcon(status: string): string {
  switch (status) {
    case 'in_progress': return '\u25B6'
    case 'waiting': return '\u23F8'
    case 'backlog': return '\u25CB'
    case 'done': return '\u2713'
    default: return '\u25CB'
  }
}

export function ActiveTasks() {
  const { data: tasks, isLoading, error } = useActiveTasks()

  const active = tasks?.filter((t) => t.status !== 'done') ?? []

  return (
    <section className="mb-10">
      <h2 className="text-2xl font-heading mb-4 text-text-dim">Tasks</h2>
      {isLoading && <p className="text-muted text-sm">Loading...</p>}
      {error && <p className="text-red text-sm">Failed to load</p>}
      {!isLoading && active.length === 0 && (
        <p className="text-muted text-sm">No active tasks.</p>
      )}
      {active.length > 0 && (
        <div className="space-y-2">
          {active.map((task) => (
            <div
              key={task.id}
              className="flex items-center gap-3 p-3 rounded-lg bg-surface
                         border border-border"
            >
              <span className="text-sm w-5 text-center text-text-dim">
                {statusIcon(task.status)}
              </span>
              <span className="flex-1 text-sm truncate">{task.title}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${priorityBadge(task.priority)}`}>
                {task.priority}
              </span>
              {task.due_date && (
                <span className="text-xs text-muted">
                  Due {task.due_date}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
