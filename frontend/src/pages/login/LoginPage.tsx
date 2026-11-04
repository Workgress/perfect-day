import { useLocation, useNavigate } from 'react-router'
import type { RedirectState } from '@/app/router/guards'
import { paths } from '@/app/router/paths'
import { OnboardingPreview } from '@/app/layouts/OnboardingPreview'
import { Button } from '@/shared/ui/button/Button'
import { ArrowRightIcon } from '@/shared/ui/icon/icons'
import { OnboardingIntro, OnboardingShell } from '@/shared/ui/onboarding/OnboardingShell'
import { useSessionStore } from '@/stores/session'

const DEMO_SESSION = {
  accessToken: 'demo-token',
  user: { name: 'Анна', birthDate: null, chronotype: null },
}

export function LoginPage() {
  const signIn = useSessionStore((state) => state.signIn)
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as RedirectState | null)?.from ?? paths.today

  const handleSignIn = () => {
    signIn(DEMO_SESSION)
    navigate(from, { replace: true })
  }

  return (
    <OnboardingShell step={1} preview={<OnboardingPreview />}>
      <title>Вход · Идеальный день</title>
      <OnboardingIntro
        title="Планируйте день по своим ритмам"
        description="Учтём биоритмы, хронотип и ваши задачи — первое расписание будет готово за пару минут."
      />
      <Button onClick={handleSignIn}>
        Войти
        <ArrowRightIcon />
      </Button>
    </OnboardingShell>
  )
}
