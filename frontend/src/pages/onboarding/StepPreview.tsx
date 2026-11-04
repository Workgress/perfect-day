import type { CSSProperties } from 'react'
import { useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { TASK_TYPES } from '@/shared/model/onboarding'
import { Button } from '@/shared/ui/button/Button'
import { ArrowRightIcon } from '@/shared/ui/icon/icons'
import { PreviewCard } from '@/shared/ui/onboarding/PreviewCard'
import { useSessionStore } from '@/stores/session'
import { CHRONOTYPES, dayTicks, dayWindows } from './chronotype'
import { demoSlots, formatTime, isTime, minutes } from './model'
import styles from './StepPreview.module.css'

export function DayWindowsPreview() {
  const draft = useSessionStore((state) => state.onboarding)
  const start = minutes(draft.workStart)
  const end = minutes(draft.workEnd)
  const validWindow = isTime(draft.workStart) && isTime(draft.workEnd) && end > start
  const windows = dayWindows(draft.chronotype, draft.workStart, draft.workEnd)
  const height = Math.max(520, ((end - start) / 60) * 52)
  const position = (time: number) => ((time - start) / (end - start)) * height

  return (
    <PreviewCard
      title="Окна вашего дня"
      footer="Предварительные окна по хронотипу, без учёта биоритмов. Показана только часть внутри выбранного дня."
    >
      <p className={`text-body-s ${styles.secondary}`}>
        {CHRONOTYPES.find((item) => item.value === draft.chronotype)?.label} · {draft.workStart}–
        {draft.workEnd}
      </p>
      {validWindow ? (
        <div className={styles.timeline} style={{ height: height + 24 }}>
          {dayTicks(start, end).map((time) => (
            <div key={time} className={styles.tick} style={{ top: position(time) }}>
              <span>{formatTime(time)}</span>
              <span />
            </div>
          ))}
          {windows.map((window) => (
            <div
              key={window.start}
              className={styles.window}
              data-type={window.type}
              data-compact={position(window.end) - position(window.start) < 48 || undefined}
              aria-label={`${window.label}: ${formatTime(window.start)}–${formatTime(window.end)}`}
              title={`${window.label}: ${formatTime(window.start)}–${formatTime(window.end)}`}
              style={{
                top: position(window.start) + 10,
                height: position(window.end) - position(window.start) - 4,
              }}
            >
              <span aria-hidden="true" />
              <span className={styles.windowLabel}>{window.label}</span>
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
