import { useEffect, type ReactNode } from 'react'
import { useLocation } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiError } from '@/shared/api/errors'
import { getProfile, PROFILE_QUERY_KEY } from '@/shared/api/profile'
import { Button } from '@/shared/ui/button/Button'
import { FormMessage } from '@/shared/ui/form-field/FormField'
import { OnboardingShell } from '@/shared/ui/onboarding/OnboardingShell'
import { useSessionStore } from '@/stores/session'
import { restoreSession, startSessionSync } from './session'
import { LogoutButton } from './LogoutButton'

export function SessionGate({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const status = useSessionStore((state) => state.status)
  const user = useSessionStore((state) => state.user)
  const generation = useSessionStore((state) => state.generation)
  const client = useQueryClient()
  const verification = pathname === '/verify-email'
  const bootstrap = useQuery({
    queryKey: ['session', 'restore', generation],
    queryFn: restoreSession,
    enabled: status === 'restoring' && !verification,
    retry: false,
    staleTime: Infinity,
  })
  const profile = useQuery({
    queryKey: [...PROFILE_QUERY_KEY, generation],
    queryFn: async ({ signal }) => {
      const document = await getProfile(signal)
      if (
        useSessionStore.getState().generation === generation &&
        useSessionStore.getState().accessToken
      )
        useSessionStore.getState().applyProfile(document)
      return document
    },
    enabled: status === 'authenticated' && !user && !verification,
    retry: false,
  })

  useEffect(startSessionSync, [])
  useEffect(() => {
    return useSessionStore.subscribe((state, previous) => {
      if (state.generation !== previous.generation) {
        void client.cancelQueries({
          predicate: (query) =>
            query.queryKey[0] !== 'session' || query.queryKey.at(-1) !== state.generation,
        })
        client.removeQueries({
          predicate: (query) =>
            query.queryKey[0] !== 'session' || query.queryKey.at(-1) !== state.generation,
        })
      }
    })
  }, [client])

  if (verification || pathname === '/dev/kit') return children
  const waiting = status === 'restoring' || (status === 'authenticated' && !user)
  if (!waiting) return children
  const active = status === 'restoring' ? bootstrap : profile
  return (
    <OnboardingShell step={1}>
      <h1 className="text-heading">
        {active.isError ? 'Не удалось загрузить данные' : 'Восстанавливаем сессию'}
      </h1>
      {active.isError ? (
        <>
          <FormMessage>{apiError(active.error)}</FormMessage>
          <Button onClick={() => void active.refetch()}>Повторить</Button>
          <LogoutButton />
        </>
      ) : (
        <p role="status">Подождите, загружаем ваш профиль…</p>
      )}
    </OnboardingShell>
  )
}
