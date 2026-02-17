import { useCallback, useEffect, useState } from 'react'
import { Header } from './components/header'
import { NeedsReply } from './components/needs-reply'
import { ActiveTasks } from './components/active-tasks'
import { Commitments } from './components/commitments'
import { Search } from './components/search'
import { useSprints } from './hooks/use-focus-data'

function SprintBanner() {
  const { data: sprints } = useSprints()
  const sprint = sprints?.[0]
  if (!sprint) return null

  const daysLeft = Math.max(
    0,
    Math.ceil((new Date(sprint.ends_at).getTime() - Date.now()) / 86_400_000)
  )

  return (
    <div className="mx-6 mb-6 px-4 py-2 rounded-lg bg-emerald-dim/30 border border-emerald-dim/50 text-sm">
      <span className="text-emerald font-medium">{sprint.name}</span>
      {sprint.project_name && (
        <span className="text-text-dim"> &middot; {sprint.project_name}</span>
      )}
      <span className="text-muted ml-2">{daysLeft}d left</span>
    </div>
  )
}

export default function App() {
  const [searchOpen, setSearchOpen] = useState(false)

  const openSearch = useCallback(() => setSearchOpen(true), [])
  const closeSearch = useCallback(() => setSearchOpen(false), [])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setSearchOpen((prev) => !prev)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  return (
    <div className="max-w-3xl mx-auto min-h-screen">
      <Header onSearchOpen={openSearch} />
      <SprintBanner />
      <main className="px-6 pb-16">
        <NeedsReply />
        <ActiveTasks />
        <Commitments />
      </main>
      <Search isOpen={searchOpen} onClose={closeSearch} />
    </div>
  )
}
