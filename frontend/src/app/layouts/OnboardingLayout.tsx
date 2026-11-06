import { Navigate, Outlet, useLocation } from 'react-router'
import { paths } from '@/app/router/paths'
import { OnboardingShell, type OnboardingStepNumber } from '@/shared/ui/onboarding/OnboardingShell'
import { DayWindowsPreview, FirstTasksPreview } from '@/pages/onboarding/StepPreview'
import { onboardingPath } from '@/app/router/onboardingPath'
import { useSessionStore } from '@/stores/session'
import { OnboardingPreview } from './OnboardingPreview'

const STEPS: Readonly<Record<string, OnboardingStepNumber>> = {
  [paths.onboarding.birthDate]: 2,
  [paths.onboarding.chronotype]: 3,
  [paths.onboarding.firstTasks]: 4,
}

export function OnboardingLayout() {
  const location = useLocation()
  const { pathname } = location
  const current = STEPS[pathname] ?? 2
  const nextStep = useSessionStore((state) => state.nextStep)

  if (current > (STEPS[onboardingPath(nextStep)] ?? 2)) {
    return <Navigate to={onboardingPath(nextStep)} replace state={location.state} />
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
