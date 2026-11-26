import type { ReactNode, Ref } from 'react'
import { cx } from '@/shared/lib/cx'
import { Brand } from '@/shared/ui/brand/Brand'
import styles from './OnboardingShell.module.css'

export type OnboardingStepNumber = 1 | 2 | 3 | 4

type OnboardingShellProps = {
  step: OnboardingStepNumber
  children: ReactNode
  preview?: ReactNode
  account?: boolean
}

export function OnboardingShell({
  step,
  children,
  preview,
  account = false,
}: OnboardingShellProps) {
  return (
    <main
      className={styles.page}
      data-auth={step === 1 || undefined}
      data-account={account || undefined}
    >
      <div className={cx(styles.layout, !preview && styles.withoutPreview)}>
        <div className={styles.content} data-auth={step === 1 || undefined}>
          <header className={styles.header}>
            <Brand className={styles.brand} />
            {!account ? (
              <div
                className={styles.progress}
                role="progressbar"
                aria-label="Онбординг"
                aria-valuemin={1}
                aria-valuemax={4}
                aria-valuenow={step}
                aria-valuetext={`Шаг ${step} из 4`}
              >
                <span className="text-caption">Шаг {step} из 4</span>
                <span className={styles.segments} aria-hidden="true">
                  {[1, 2, 3, 4].map((number) => (
                    <span
                      key={number}
                      className={styles.segment}
                      data-complete={number <= step || undefined}
                    />
                  ))}
                </span>
              </div>
            ) : null}
          </header>
          <div className={styles.body}>{children}</div>
        </div>
        {preview ? (
          <aside className={styles.preview} aria-label="Предпросмотр">
            {preview}
          </aside>
        ) : null}
      </div>
    </main>
  )
}

export function OnboardingIntro({
  title,
  description,
  headingRef,
}: {
  title: string
  description: string
  headingRef?: Ref<HTMLHeadingElement>
}) {
  return (
    <div className={styles.intro}>
      <h1
        ref={headingRef}
        tabIndex={headingRef ? -1 : undefined}
        className={cx('text-display', styles.title)}
      >
        {title}
      </h1>
      <p className={cx('text-body', styles.description)}>{description}</p>
    </div>
  )
}
