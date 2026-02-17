import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

export function useNeedsReply() {
  return useQuery({
    queryKey: ['needs-reply'],
    queryFn: api.needsReply,
    refetchInterval: 60_000,
  })
}

export function useActiveTasks() {
  return useQuery({
    queryKey: ['tasks'],
    queryFn: () => api.tasks(),
    refetchInterval: 60_000,
  })
}

export function useCommitments() {
  return useQuery({
    queryKey: ['commitments'],
    queryFn: () => api.commitments('open'),
    refetchInterval: 60_000,
  })
}

export function useSprints() {
  return useQuery({
    queryKey: ['sprints'],
    queryFn: api.sprints,
    refetchInterval: 60_000,
  })
}
