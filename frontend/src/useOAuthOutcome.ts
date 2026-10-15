import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'

export interface Outcome {
  ok: boolean
  message: string
}

/** How connecting went, from ?<param>= on a provider's way back through the API (e.g. routers/gmail.py), shown
 * once: the parameter is then removed. An unknown code shows `fallback`. */
export function useOAuthOutcome(param: string, outcomes: Record<string, Outcome>, fallback: string) {
  const [params, setParams] = useSearchParams()
  const [outcome] = useState(() => {
    const value = params.get(param)
    return value ? (outcomes[value] ?? outcomes[fallback]) : null
  })
  useEffect(() => {
    if (!params.has(param)) return
    params.delete(param)
    setParams(params, { replace: true, preventScrollReset: true })
  }, [param, params, setParams])
  return outcome
}
