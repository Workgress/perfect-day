import { useLocation } from 'react-router'
import type { RedirectState } from '@/app/router/guards'
import { paths } from '@/app/router/paths'
import { OnboardingPreview } from '@/app/layouts/OnboardingPreview'
import { OnboardingIntro, OnboardingShell } from '@/shared/ui/onboarding/OnboardingShell'
import { AuthForm } from './AuthForm'
import { getAuthRedirectPath } from './auth'

export function LoginPage() {
  const location = useLocation()
  const mode = location.pathname === paths.register ? 'register' : 'login'
  const state = location.state as
    (RedirectState & { email?: string; passwordReset?: boolean }) | null
  const from = getAuthRedirectPath(state?.from)
  const initialEmail = typeof state?.email === 'string' ? state.email : ''

  return (
    <OnboardingShell step={1} account={mode === 'register'} preview={<OnboardingPreview />}>
      <title>
        {mode === 'register' ? 'Регистрация · Идеальный день' : 'Вход · Идеальный день'}
      </title>
      <OnboardingIntro
        title={mode === 'register' ? 'Создайте аккаунт' : 'Планируйте день по своим ритмам'}
        description={
          mode === 'register'
            ? 'Сохраните свой ритм, задачи и настройки. После регистрации подтвердите почту.'
            : 'Учтём биоритмы, хронотип и ваши задачи — первое расписание будет готово за пару минут.'
        }
      />
      <AuthForm
        key={mode}
        mode={mode}
        initialEmail={initialEmail}
        redirectTo={from}
        passwordReset={state?.passwordReset}
      />
    </OnboardingShell>
  )
}
