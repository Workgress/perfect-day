import { useEffect, useState, type CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { onboardingRequest } from '@/shared/api/profile'
import { previewPlan } from '@/shared/api/plan'
import { HttpError } from '@/shared/api/http'
import { apiError } from '@/shared/api/errors'
import { FormMessage } from '@/shared/ui/form-field/FormField'
import { Button } from '@/shared/ui/button/Button'
import { PreviewCard } from '@/shared/ui/onboarding/PreviewCard'
import { useSessionStore } from '@/stores/session'
import { CHRONOTYPES, dayTicks, dayWindows } from './chronotype'
import { formatTime, isTime, minutes, validateTasks } from './model'
import { localPlanPreview } from './planPreview'
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
  const draft = useSessionStore((state) => state.onboarding)
  const timezone = useSessionStore((state) => state.timezone)
  const generation = useSessionStore((state) => state.generation)
  const body = onboardingRequest(draft.tasks, timezone)
  const snapshot = JSON.stringify({
    body,
    chronotype: draft.chronotype,
    workStart: draft.workStart,
    workEnd: draft.workEnd,
    timezone,
  })
  const [settled, setSettled] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => setSettled(snapshot), 350)
    return () => clearTimeout(timer)
  }, [snapshot])
  const valid = !validateTasks(draft)
  const query = useQuery({
    queryKey: ['onboarding-preview', generation, snapshot],
    queryFn: async ({ signal }) => {
      try {
        return await previewPlan(body, signal)
      } catch (error) {
        if (!(error instanceof HttpError) || error.status !== 404) throw error
        signal.throwIfAborted()
        return localPlanPreview(body, draft, timezone)
      }
    },
    enabled: valid && settled === snapshot,
    retry: false,
    staleTime: 30_000,
    gcTime: 0,
    refetchOnWindowFocus: false,
  })
  const preview = valid ? query.data : undefined
  const rows = preview
    ? [
        ...preview.slots.map((slot) => ({
          task: body.tasks[slot.task_index],
          index: slot.task_index,
          time: `${slot.start_time.slice(0, 5)}–${slot.end_time.slice(0, 5)}`,
          explanation: slot.explanation,
        })),
        ...preview.unscheduled_task_indexes.map((index) => ({
          task: body.tasks[index],
          index,
          time: 'Время не определено',
          explanation:
            'Задача не помещается в доступные окна. Измените длительность или режим дня.',
        })),
      ]
    : []

  return (
    <PreviewCard
      title="Ваш план на сегодня"
      footer={
        preview?.local
          ? 'Предварительная раскладка по хронотипу. Биоритмы пока не учитываются; это ещё не сохранённый план.'
          : 'Предпросмотр не сохраняет задачи. Итоговый план подтвердится после нажатия «Составить план».'
      }
    >
      {!draft.tasks.length ? (
        <p className={`text-body-s ${styles.secondary}`}>
          Добавьте свои задачи и нажмите «Составить план», чтобы сохранить их и завершить настройку.
        </p>
      ) : null}
      {draft.tasks.length && !valid ? (
        <p className={`text-body-s ${styles.secondary}`}>
          Заполните задачи и проверьте длительность, чтобы увидеть время выполнения.
        </p>
      ) : null}
      {valid && !preview && !query.isError ? (
        <p className={`text-body-s ${styles.secondary}`} role="status">
          Составляем предпросмотр…
        </p>
      ) : null}
      {query.isError && valid ? (
        <>
          <FormMessage>{apiError(query.error)}</FormMessage>
          <Button variant="secondary" onClick={() => query.refetch()}>
            Повторить расчёт
          </Button>
        </>
      ) : null}
      {rows.map((slot) => (
        <div
          key={slot.index}
          className={styles.slot}
          style={{ '--slot-color': `var(--type-${slot.task.type})` } as CSSProperties}
        >
          <span className={styles.dot} aria-hidden="true" />
          <div>
            <p className={`text-mono-s-medium ${styles.slotTime}`}>{slot.time}</p>
            <p className={`text-label ${styles.taskTitle}`}>{slot.task.title}</p>
            <p className={`text-caption ${styles.secondary}`}>{slot.explanation}</p>
          </div>
        </div>
      ))}
    </PreviewCard>
  )
}
