import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { localDate } from '@/shared/lib/dateTime'
import type { ScheduleSlot, SchedulePlanningDetails } from '@/shared/model/schedule'
import { TASK_TYPES, type Task } from '@/shared/model/task'
import { Button } from '@/shared/ui/button/Button'
import {
  ArrowRightIcon,
  CheckIcon,
  ClockIcon,
  GripVerticalIcon,
  LockIcon,
  SparklesIcon,
  XIcon,
} from '@/shared/ui/icon/icons'
import { REMINDER_OPTIONS, WEEKDAYS, type TaskFormOptions } from './taskFormSettings'
import { timelineClock, timelineDuration } from './timelineModel'
import { useTaskDialog } from './useTaskDialog'
import { taskPlacementExplanation } from './taskPlacementExplanation'
import { plannerMessage, plannerExplanation } from '@/shared/lib/plannerText'
import styles from './TaskDetailsPanel.module.css'

type TaskDetailsPanelProps = {
  task: Task
  slots: ScheduleSlot[]
  planning?: SchedulePlanningDetails
  timezone: string
  now?: Date
  options?: TaskFormOptions
  onClose: () => void
  onEdit: () => void
  onMove?: () => void
  onPin?: () => void
  onStart?: () => void
  onComplete?: () => void
  onSkip?: () => void
  onReopen?: () => void
  placementAction?: ReactNode
  recoveryAction?: ReactNode
  explanationState?: ReactNode
  actionsDisabled?: boolean
  notice?: string | null
  deleteAction?: ReactNode
  exampleExplanation?: boolean
  placementMessage?: string
  busy?: boolean
}

const PRIORITIES = { low: 'Низкий', medium: 'Средний', high: 'Высокий' }

// Temporary copy from v4 light · 2.4, requested for the panel preview.
const EXAMPLE_REASONS = [
  'Интеллектуальный цикл сегодня +95 % — хорошее время для сложной работы.',
  '10:00–12:00 — ваше утреннее окно продуктивности (жаворонок).',
  'После неё — перерыв 30 минут: 90 минут фокуса подряд.',
]

function repeatLabel(options?: TaskFormOptions) {
  if (!options) return 'Не указано'
  const recurrence = options.recurrence
  if (!recurrence) return 'Не повторять'
  if (recurrence.frequency === 'daily') return 'Каждый день'
  return `Каждые ${recurrence.interval} нед. · ${recurrence.weekdays.map((day) => WEEKDAYS[day - 1]).join(', ')}`
}

export function TaskDetailsPanel({
  task,
  slots,
  planning,
  timezone,
  now: suppliedNow,
  options,
  onClose,
  onEdit,
  onMove,
  onPin,
  onStart,
  onComplete,
  onSkip,
  onReopen,
  placementAction,
  recoveryAction,
  explanationState,
  actionsDisabled = false,
  notice,
  deleteAction,
  exampleExplanation = false,
  placementMessage,
  busy = false,
}: TaskDetailsPanelProps) {
  const [openedAt] = useState(() => new Date())
  const now = suppliedNow ?? openedAt
  const titleId = useId()
  const moveButton = useRef<HTMLButtonElement>(null)
  const hadPlacement = useRef(false)
  const placementOpen = !!placementAction
  useEffect(() => {
    if (hadPlacement.current && !placementOpen) moveButton.current?.focus()
    hadPlacement.current = placementOpen
  }, [placementOpen])
  const { dialogRef, onKeyDown } = useTaskDialog(
    () => {
      if (!busy) onClose()
    },
    '[data-task-details-trigger]',
    '[data-panel-title]',
  )
  const placements = slots
    .filter((slot) => slot.kind === 'task' && slot.task_id === task.id)
    .sort((a, b) => Date.parse(a.start_at) - Date.parse(b.start_at))
  const first = placements[0]
  const last = placements.at(-1)
  const finished = task.status === 'done' || task.status === 'skipped'
  const Marker =
    task.status === 'done'
      ? CheckIcon
      : task.is_pinned
        ? LockIcon
        : first
          ? SparklesIcon
          : ClockIcon
  const status =
    task.status === 'done'
      ? 'выполнена'
      : task.status === 'skipped'
        ? 'пропущена'
        : task.actual_start
          ? 'начата'
          : task.is_pinned
            ? 'время закреплено'
            : first
              ? 'поставлено алгоритмом'
              : placementMessage
                ? task.status === 'scheduled'
                  ? 'запланирована'
                  : 'ожидает размещения'
                : 'не распределено'
  const dateLabel = new Intl.DateTimeFormat('ru-RU', {
    timeZone: 'UTC',
    weekday: 'short',
    day: 'numeric',
    month: 'long',
  }).format(new Date(`${task.planned_date}T12:00:00Z`))
  const clock = (at: string) => timelineClock(Date.parse(at), timezone)
  const deadline = task.deadline
    ? `${localDate(new Date(task.deadline), timezone) === localDate(now, timezone) ? 'сегодня' : new Intl.DateTimeFormat('ru-RU', { timeZone: timezone, day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(task.deadline))}, до ${clock(task.deadline)}`
    : 'Без срока'
  const reasons = [
    ...new Set(placements.map((slot) => taskPlacementExplanation(task, slot, timezone, planning))),
  ]
  const unplaced = planning?.unscheduled_explanations.find(
    (item) => item.task_id === task.id && item.planned_date === task.planned_date,
  )
  if (!placements.length && unplaced) reasons.push(plannerExplanation(unplaced.explanation))
  const nextRest = last
    ? slots.find(
        (slot) => slot.kind !== 'task' && Date.parse(slot.start_at) === Date.parse(last.end_at),
      )
    : undefined
  if (nextRest)
    reasons.push(
      `После задачи — ${nextRest.kind === 'lunch' ? 'обед' : nextRest.kind === 'break' ? 'перерыв' : 'отдых'} ${timelineDuration((Date.parse(nextRest.end_at) - Date.parse(nextRest.start_at)) / 60_000)}.`,
    )
  const displayedReasons = exampleExplanation ? EXAMPLE_REASONS : reasons
  const reminder = options
    ? (REMINDER_OPTIONS.find(
        (item) =>
          item.value === (options.reminderMinutes === null ? '' : String(options.reminderMinutes)),
      )?.label ?? 'Не указано')
    : 'Не указано'

  return (
    <dialog
      ref={dialogRef}
      className={styles.dialog}
      data-type={task.type}
      aria-modal="true"
      aria-labelledby={titleId}
      onKeyDown={onKeyDown}
      onCancel={(event) => {
        event.preventDefault()
        if (!busy) onClose()
      }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return
        const bounds = event.currentTarget.getBoundingClientRect()
        if (
          event.clientX < bounds.left ||
          event.clientX > bounds.right ||
          event.clientY < bounds.top ||
          event.clientY > bounds.bottom
        )
          if (!busy) onClose()
      }}
    >
      <div className={styles.panel}>
        <button
          type="button"
          className={styles.grabber}
          disabled={busy}
          aria-label="Закрыть задачу"
          onClick={onClose}
        >
          <span />
        </button>
        <header className={styles.header}>
          <div className={styles.tags}>
            <span className={styles.type}>
              <span aria-hidden="true" />
              {TASK_TYPES[task.type]}
            </span>
            <span className={styles.status}>
              <Marker size={14} />
              {status}
            </span>
          </div>
          <Button
            variant="secondary"
            className={styles.close}
            disabled={busy}
            aria-label="Закрыть задачу"
            onClick={onClose}
          >
            <XIcon size={18} />
          </Button>
        </header>
        <div className={styles.heading}>
          <h2 id={titleId} className={styles.title} tabIndex={-1} data-panel-title>
            {task.title}
          </h2>
          <div className={styles.time}>
            <strong>
              {first
                ? placements
                    .map((slot) => `${clock(slot.start_at)}–${clock(slot.end_at)}`)
                    .join(', ')
                : placementMessage
                  ? 'Размещение не подтверждено'
                  : 'Время не назначено'}
            </strong>
            <span>
              {dateLabel} · {task.duration_min} мин
            </span>
          </div>
        </div>
        <dl className={styles.facts}>
          {task.actual_start ? (
            <div>
              <dt>Начата</dt>
              <dd>{clock(task.actual_start)}</dd>
            </div>
          ) : null}
          {task.is_date_locked ? (
            <div>
              <dt>Дата</dt>
              <dd>Автоматический перенос запрещён</dd>
            </div>
          ) : null}
          <div>
            <dt>Срок</dt>
            <dd>{deadline}</dd>
          </div>
          <div>
            <dt>Приоритет</dt>
            <dd>{PRIORITIES[task.priority]}</dd>
          </div>
          <div>
            <dt>Повтор</dt>
            <dd>{repeatLabel(options)}</dd>
          </div>
          <div>
            <dt>Напоминание</dt>
            <dd>{reminder}</dd>
          </div>
        </dl>
        <section
          className={styles.reasons}
          data-example={exampleExplanation || undefined}
          aria-label={unplaced && !first ? 'Почему задача без времени' : 'Почему в это время'}
        >
          <h3 className="text-label">
            {unplaced && !first ? 'Почему задача без времени' : 'Почему в это время'}
          </h3>
          {displayedReasons.length ? (
            <ul>
              {displayedReasons.map((reason, index) => (
                <li key={reason} data-reason={index}>
                  <span aria-hidden="true" />
                  <span>{reason}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p>
              {placementMessage ??
                (first
                  ? 'Объяснение размещения пока не указано.'
                  : 'Задача пока не размещена на шкале. Выберите день и время в форме редактирования.')}
            </p>
          )}
          {explanationState}
        </section>
        {task.description ? (
          <section className={styles.description} aria-label="Описание задачи">
            <h3 className="text-label">Описание</h3>
            <p>{task.description}</p>
          </section>
        ) : null}
        <>
          <Button
            className={styles.start}
            disabled={busy || actionsDisabled || finished || !!task.actual_start || !onStart}
            title={!onStart ? 'Запуск задачи пока недоступен' : undefined}
            onClick={onStart}
          >
            <ArrowRightIcon size={18} />
            {task.status === 'done'
              ? 'Выполнена'
              : task.status === 'skipped'
                ? 'Пропущена'
                : task.actual_start
                  ? 'Задача начата'
                  : 'Начать сейчас'}
          </Button>
          {onComplete || onSkip || onReopen ? (
            <div className={styles.statusActions}>
              {finished ? (
                <Button
                  variant="secondary"
                  disabled={busy || actionsDisabled || !onReopen}
                  onClick={onReopen}
                >
                  Вернуть в работу
                </Button>
              ) : (
                <>
                  <Button
                    variant="secondary"
                    disabled={busy || actionsDisabled || !onComplete}
                    onClick={onComplete}
                  >
                    <CheckIcon size={16} />
                    Выполнить
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={busy || actionsDisabled || !onSkip}
                    onClick={onSkip}
                  >
                    Пропустить
                  </Button>
                </>
              )}
            </div>
          ) : null}
          <div className={styles.actions}>
            <Button
              ref={moveButton}
              variant="secondary"
              disabled={busy || actionsDisabled || finished || !!task.actual_start || !onMove}
              onClick={onMove}
            >
              Перенести
            </Button>
            <Button
              variant="secondary"
              disabled={busy || actionsDisabled || finished || !onPin}
              title={!onPin ? 'Закрепление времени пока недоступно' : undefined}
              onClick={onPin}
            >
              {task.is_pinned ? 'Открепить' : 'Закрепить'}
            </Button>
            <Button variant="secondary" disabled={busy} onClick={onEdit}>
              Изменить
            </Button>
          </div>
        </>
        {placementAction}
        {deleteAction}
        {notice ? (
          <p className={styles.notice} role="status">
            {plannerMessage(notice)}
          </p>
        ) : null}
        {recoveryAction}
        <p className={styles.hint}>
          <GripVerticalIcon size={14} />
          Название, срок и длительность доступны по кнопке «Изменить».
        </p>
      </div>
    </dialog>
  )
}
