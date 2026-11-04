import { Outlet, useLocation } from 'react-router'
import { paths } from '@/app/router/paths'
import { OnboardingShell, type OnboardingStepNumber } from '@/shared/ui/onboarding/OnboardingShell'
import { OnboardingPreview } from './OnboardingPreview'

const STEPS: Readonly<Record<string, OnboardingStepNumber>> = {
  [paths.onboarding.birthDate]: 2,
  [paths.onboarding.chronotype]: 3,
  [paths.onboarding.firstTasks]: 4,
}

export function OnboardingLayout() {
  const { pathname } = useLocation()
  const current = STEPS[pathname] ?? 2

  return (
    <OnboardingShell step={current} preview={<OnboardingPreview />}>
      <Outlet />
    </OnboardingShell>
  )
}
