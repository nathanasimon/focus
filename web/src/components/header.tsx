import { SyncButton } from './sync-button'

interface HeaderProps {
  onSearchOpen: () => void
}

export function Header({ onSearchOpen }: HeaderProps) {
  return (
    <header className="flex items-center justify-between py-8 px-6">
      <h1 className="text-4xl font-heading tracking-tight">Focus</h1>
      <div className="flex items-center gap-3">
        <button
          onClick={onSearchOpen}
          className="px-3 py-1.5 text-sm rounded-lg border border-border
                     bg-surface hover:bg-surface-hover transition-colors
                     text-text-dim cursor-pointer flex items-center gap-2"
        >
          <kbd className="text-xs text-muted">Cmd+K</kbd>
          Search
        </button>
        <SyncButton />
      </div>
    </header>
  )
}
