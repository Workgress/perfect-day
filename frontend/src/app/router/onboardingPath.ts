import type { OnboardingStep } from '@/shared/model/profile'
import { paths } from './paths'

export function onboardingPath(step: OnboardingStep) {
  return step === 'birth_date'
    ? paths.onboarding.birthDate
    : step === 'chronotype'
      ? paths.onboarding.chronotype
      : paths.onboarding.firstTasks
}
