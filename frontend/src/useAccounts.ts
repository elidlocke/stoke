import { useQuery } from '@tanstack/react-query'
import { api } from './api'

/** Returns a lookup from account id to display name (falls back to the id while loading). */
export function useAccountNames(): (id: string) => string {
  const { data } = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  const names = new Map(data?.accounts.map((a) => [a.id, a.display_name]))
  return (id) => names.get(id) ?? id
}

/** Whether more than one account is in scope, so lists should say which account each row is from. */
export function useMultipleAccounts(): boolean {
  const { data } = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  return (data?.accounts.length ?? 0) > 1
}
