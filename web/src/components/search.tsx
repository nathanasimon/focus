import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { SearchResult } from '../lib/types'

interface SearchProps {
  isOpen: boolean
  onClose: () => void
}

export function Search({ isOpen, onClose }: SearchProps) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    if (isOpen) {
      inputRef.current?.focus()
      setQuery('')
      setResults([])
    }
  }, [isOpen])

  const search = useCallback(async (q: string) => {
    if (q.length < 2) {
      setResults([])
      return
    }
    setLoading(true)
    try {
      const res = await api.search(q)
      setResults(res)
    } catch {
      setResults([])
    } finally {
      setLoading(false)
    }
  }, [])

  const handleInput = (value: string) => {
    setQuery(value)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => search(value), 300)
  }

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    if (isOpen) window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh] bg-black/60"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl bg-surface rounded-xl border border-border shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-4 border-b border-border">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => handleInput(e.target.value)}
            placeholder="Search emails, tasks, projects..."
            className="w-full bg-transparent text-text outline-none text-base
                       placeholder:text-muted"
          />
        </div>
        <div className="max-h-80 overflow-y-auto">
          {loading && (
            <p className="p-4 text-sm text-muted">Searching...</p>
          )}
          {!loading && query.length >= 2 && results.length === 0 && (
            <p className="p-4 text-sm text-muted">No results found.</p>
          )}
          {results.map((r, i) => (
            <div
              key={`${r.collection}-${r.id}-${i}`}
              className="p-3 border-b border-border last:border-0
                         hover:bg-surface-hover transition-colors"
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs px-1.5 py-0.5 rounded bg-surface-hover text-muted">
                  {r.collection}
                </span>
                <span className="text-xs text-muted">
                  {Math.round(r.score * 100)}% match
                </span>
              </div>
              <p className="text-sm text-text-dim line-clamp-2">{r.text}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
