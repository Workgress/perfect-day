import type { ReactNode } from 'react'
import { OnboardingIntro } from '@/shared/ui/onboarding/OnboardingShell'
import styles from './OnboardingStep.module.css'

type OnboardingStepProps = {
  title: string
  description: string
  children: ReactNode
}

export function OnboardingStep({ title, description, children }: OnboardingStepProps) {
  return (
    <>
      <title>{`${title} · Идеальный день`}</title>
      <OnboardingIntro title={title} description={description} />
      <div className={styles.actions}>{children}</div>
    </>
  )
}
