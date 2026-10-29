import type { ReactNode } from 'react'
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
      <h1 className="text-title">{title}</h1>
      <p className={`text-body-s ${styles.description}`}>{description}</p>
      <div className={styles.actions}>{children}</div>
    </>
  )
}
