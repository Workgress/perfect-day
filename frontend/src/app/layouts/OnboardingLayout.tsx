import { Outlet, useLocation } from 'react-router'
import { paths } from '@/app/router/paths'
import styles from './OnboardingLayout.module.css'

const STEPS = [paths.onboarding.birthDate, paths.onboarding.chronotype, paths.onboarding.firstTasks]

export function OnboardingLayout() {
  const { pathname } = useLocation()
  const current = STEPS.findIndex((step) => step === pathname)

  return (
    <div className={styles.layout}>
      <div className={styles.card}>
        {current >= 0 ? (
          <p className={`text-caption ${styles.progress}`}>
            Шаг {current + 1} из {STEPS.length}
          </p>
        ) : null}
        <Outlet />
      </div>
    </div>
  )
}
