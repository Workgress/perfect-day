import type { CSSProperties } from 'react'
import { useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { TASK_TYPES } from '@/shared/model/onboarding'
import { Button } from '@/shared/ui/button/Button'
import { ArrowRightIcon } from '@/shared/ui/icon/icons'
import { PreviewCard } from '@/shared/ui/onboarding/PreviewCard'
import { useSessionStore } from '@/stores/session'
import { demoSlots, formatTime, minutes } from './model'
import styles from './StepPreview.module.css'

const CHRONOTYPE_LABELS = { lark: 'Жаворонок', dove: 'Голубь', owl: 'Сова' }

const WINDOWS = [
  { type: 'routine', label: 'Разгон: почта, планирование', top: 10, height: 74 },
  { type: 'intellectual', label: 'Интеллектуальное окно', top: 88, height: 126 },
  { type: 'rest', label: 'Обед и отдых', top: 218, height: 48 },
  { type: 'intellectual', label: 'Вторая волна', top: 270, height: 74 },
  { type: 'physical', label: 'Физическое окно', top: 374, height: 48 },
  { type: 'routine', label: 'Рутина', top: 426, height: 100 },
]

export function DayWindowsPreview() {
  const draft = useSessionStore((state) => state.onboarding)
  const start = minutes(draft.workStart)
  const end = minutes(draft.workEnd)
  const validWindow = end > start

  return (
    <PreviewCard
      title="Окна вашего дня"
      footer="Пример окон дня. Персональные окна пока не рассчитываются."
    >
      <p className={`text-body-s ${styles.secondary}`}>
        {CHRONOTYPE_LABELS[draft.chronotype]} · {draft.workStart}–{draft.workEnd}
      </p>
      {validWindow ? (
        <div className={styles.timeline}>
          {Array.from({ length: 11 }, (_, index) => (
            <div key={index} className={styles.tick} style={{ top: index * 52 }}>
              <span>{formatTime(Math.round(start + ((end - start) * index) / 10))}</span>
              <span />
            </div>
          ))}
          {WINDOWS.map((window) => (
            <div
              key={window.top}
              className={styles.window}
              data-type={window.type}
              style={{ top: window.top, height: window.height }}
            >
              <span aria-hidden="true" />
              {window.label}
            </div>
          ))}
        </div>
      ) : (
        <p className={`text-caption ${styles.secondary}`}>Выберите конец дня позже начала.</p>
      )}
    </PreviewCard>
  )
}

export function FirstTasksPreview() {
  const navigate = useNavigate()
  const draft = useSessionStore((state) => state.onboarding)
  const complete = useSessionStore((state) => state.completeOnboarding)
  const slots = draft.planReady ? demoSlots(draft) : []

  return (
    <PreviewCard
      title="Ваш план на сегодня"
      footer="Пример распределения задач. Биоритмы и хронотип пока не учитываются."
    >
      {!slots.length ? (
        <p className={`text-body-s ${styles.secondary}`}>
          Добавьте свои задачи и нажмите «Составить план», чтобы увидеть пример распределения по
          времени.
        </p>
      ) : null}
      {slots.map((slot) => (
        <div
          key={slot.id}
          className={styles.slot}
          style={{ '--slot-color': `var(--type-${slot.type})` } as CSSProperties}
        >
          <span className={styles.dot} aria-hidden="true" />
          <div>
            <p className="text-mono-s">
              {slot.start}–{slot.end}
            </p>
            <p className={`text-label ${styles.taskTitle}`}>{slot.title}</p>
            <p className={`text-caption ${styles.secondary}`}>
              {TASK_TYPES[slot.type]} · {slot.durationMin} мин
            </p>
          </div>
        </div>
      ))}
      {draft.planReady && import.meta.env.DEV ? (
        <Button
          className={styles.openPlan}
          variant="secondary"
          onClick={() => {
            complete()
            navigate(paths.today, { replace: true })
          }}
        >
          <ArrowRightIcon />
          Открыть план
        </Button>
      ) : null}
    </PreviewCard>
  )
}
