import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { useMutation } from '@tanstack/react-query'
import { paths } from '@/app/router/paths'
import { announceLogin } from '@/app/session'
import { requestTokens } from '@/shared/api/auth'
import { apiError } from '@/shared/api/errors'
import { Button } from '@/shared/ui/button/Button'
import { FormMessage } from '@/shared/ui/form-field/FormField'
import { OnboardingIntro, OnboardingShell } from '@/shared/ui/onboarding/OnboardingShell'
import { useSessionStore } from '@/stores/session'

export function VerifyEmailPage() {
  const navigate = useNavigate()
  const [token, setToken] = useState(
    () => new URLSearchParams(window.location.hash.slice(1)).get('token') ?? '',
  )
  const [error, setError] = useState('')
  const mutation = useMutation({
    mutationFn: () => requestTokens('/auth/verify-email', { token }),
    retry: false,
    gcTime: 0,
  })
  useEffect(() => {
    window.history.replaceState(
      window.history.state,
      '',
      window.location.pathname + window.location.search,
    )
  }, [])
  return (
    <OnboardingShell step={1}>
      <title>Подтверждение почты · Идеальный день</title>
      <OnboardingIntro
        title="Подтвердите почту"
        description="Нажмите кнопку, чтобы подтвердить адрес и продолжить настройку."
      />
      {!token ? (
        <FormMessage>
          В ссылке нет токена подтверждения. Запросите новое письмо на странице входа.
        </FormMessage>
      ) : null}
      {error ? <FormMessage>{error}</FormMessage> : null}
      <Button
        disabled={!token || mutation.isPending}
        onClick={() => {
          setError('')
          mutation.mutate(undefined, {
            onSuccess: (result) => {
              setToken('')
              useSessionStore
                .getState()
                .signIn({ accessToken: result.access_token, expiresIn: result.expires_in })
              announceLogin()
              navigate(paths.today, { replace: true })
            },
            onError: (reason) => setError(apiError(reason)),
            onSettled: () => mutation.reset(),
          })
        }}
      >
        {mutation.isPending ? 'Подтверждаем…' : 'Подтвердить почту'}
      </Button>
      <Link to={paths.login}>Вернуться ко входу</Link>
    </OnboardingShell>
  )
}
