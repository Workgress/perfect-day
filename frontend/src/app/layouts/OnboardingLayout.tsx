import { Navigate, Outlet, useLocation } from 'react-router'
import { paths } from '@/app/router/paths'
import { OnboardingShell, type OnboardingStepNumber } from '@/shared/ui/onboarding/OnboardingShell'
import { DayWindowsPreview, FirstTasksPreview } from '@/pages/onboarding/StepPreview'
import { parseBirthDate } from '@/pages/onboarding/model'
import { useSessionStore } from '@/stores/session'
import { OnboardingPreview } from './OnboardingPreview'

const STEPS: Readonly<Record<string, OnboardingStepNumber>> = {
  [paths.onboarding.birthDate]: 2,
  [paths.onboarding.chronotype]: 3,
  [paths.onboarding.firstTasks]: 4,
}

export function OnboardingLayout() {
  const { pathname } = useLocation()
  const current = STEPS[pathname] ?? 2
  const draft = useSessionStore((state) => state.onboarding)
  const user = useSessionStore((state) => state.user)

  if (current > 2 && !parseBirthDate(draft.birthDate)) {
    return <Navigate to={paths.onboarding.birthDate} replace />
  }
  if (current > 3 && !user?.chronotype) {
    return <Navigate to={paths.onboarding.chronotype} replace />
  }

  return (
    <OnboardingShell
      step={current}
      preview={
        current === 3 ? (
          <DayWindowsPreview />
        ) : current === 4 ? (
          <FirstTasksPreview />
        ) : (
          <OnboardingPreview profile />
        )
      }
    >
      <Outlet />
    </OnboardingShell>
  )
}
