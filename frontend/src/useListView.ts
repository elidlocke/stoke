import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router'

/**
 * URL-backed state for a list page: one option picked from `options` (stored under `param`)
 * plus the account filter, so filtered views can be linked and survive reloads.
 */
export function useListParams<T extends string>(param: string, options: { value: T }[], fallback: T) {
  const [params, setParams] = useSearchParams()
  const value = options.find((o) => o.value === params.get(param))?.value ?? fallback
  const account = params.get('account') || undefined

  const update = (next: Record<string, string | undefined>) => {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(next)) {
      if (v) p.set(k, v)
      else p.delete(k)
    }
    setParams(p, { replace: true })
  }

  return {
    value,
    account,
    setValue: (v: T) => update({ [param]: v }),
    setAccount: (a: string | undefined) => update({ account: a }),
  }
}

/** A query whose `refresh` bypasses the backend's Stripe cache and replaces the cached result. */
export function useRefreshableQuery<T>(queryKey: unknown[], fetcher: (refresh: boolean) => Promise<T>) {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey, queryFn: () => fetcher(false) })

  const refresh = async () => {
    const data = await queryClient.fetchQuery({
      queryKey: [...queryKey, 'refresh'],
      queryFn: () => fetcher(true),
      staleTime: 0,
    })
    queryClient.setQueryData(queryKey, data)
  }

  return { query, refresh }
}
