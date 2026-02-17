import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'

export function SyncButton() {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: api.sync,
    onSuccess: () => {
      queryClient.invalidateQueries()
    },
  })

  return (
    <button
      onClick={() => mutation.mutate()}
      disabled={mutation.isPending}
      className="px-3 py-1.5 text-sm rounded-lg border border-border
                 bg-surface hover:bg-surface-hover transition-colors
                 disabled:opacity-50 cursor-pointer disabled:cursor-wait"
    >
      {mutation.isPending ? (
        <span className="flex items-center gap-2">
          <Spinner />
          Syncing...
        </span>
      ) : mutation.isSuccess ? (
        <span className="text-emerald">
          Synced ({mutation.data.emails_fetched} new)
        </span>
      ) : mutation.isError ? (
        <span className="text-red">Sync failed</span>
      ) : (
        'Sync'
      )}
    </button>
  )
}

function Spinner() {
  return (
    <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}
