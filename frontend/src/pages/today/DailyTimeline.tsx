import { useEffect, useId, useState } from 'react'
import type { DailySchedule } from '@/shared/model/schedule'
import { TASK_TYPES, type Task } from '@/shared/model/task'
import { Button } from '@/shared/ui/button/Button'
import {
  AlertTriangleIcon,
  CalendarIcon,
  CheckIcon,
  ChevronDownIcon,
  CoffeeIcon,
  GripVerticalIcon,
  LinkIcon,
  LockIcon,
  MoonIcon,
  PlusIcon,
  SparklesIcon,
} from '@/shared/ui/icon/icons'
import { buildTimeline, SYSTEM_SLOT_LABELS, timelineClock, timelineDuration } from './timelineModel'
import styles from './DailyTimeline.module.css'
import { TaskDayList } from './TaskDayList'

type DailyTimelineProps = {
  day: DailySchedule
  now?: Date
  onTaskSelect?: (task: Task) => void
  selectedTaskId?: string | null
  onCreateTask?: (date: string, preferredStart?: string) => void
  onImportCalendar?: () => void
}

function taskCount(count: number) {
  const plural = new Intl.PluralRules('ru-RU').select(count)
  return `${count} ${plural === 'one' ? 'задача' : plural === 'few' ? 'задачи' : 'задач'}`
}

function useTimelineClock(fixed?: Date) {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    if (fixed) return
    const update = () => setNow(new Date())
    const interval = window.setInterval(update, 30_000)
    window.addEventListener('focus', update)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('focus', update)
    }
  }, [fixed])
  return fixed ?? now
}

export function DailyTimeline(props: DailyTimelineProps) {
  return <TimelineContent key={`${props.day.date}:${props.day.timezone}`} {...props} />
}

function TimelineContent({
  day,
  now: fixedNow,
  onTaskSelect,
  selectedTaskId,
  onCreateTask,
  onImportCalendar,
}: DailyTimelineProps) {
  const now = useTimelineClock(fixedNow)
  const [showCompleted, setShowCompleted] = useState(false)
  const id = useId()
  let timeline: ReturnType<typeof buildTimeline>
  try {
    timeline = buildTimeline(day, showCompleted, now)
  } catch (error) {
    return (
      <section className={styles.error} role="alert">
        <AlertTriangleIcon size={20} />
        <div>
          <h2 className="text-heading">Не удалось показать план дня</h2>
          <p>{error instanceof Error ? error.message : 'Проверьте данные расписания.'}</p>
        </div>
      </section>
    )
  }
  const clock = (at: number) => timelineClock(at, day.timezone)
  const range = (start: number, end: number) => `${clock(start)}–${clock(end)}`
  const taskIds = new Set(
    day.slots.filter((slot) => slot.kind === 'task').map((slot) => slot.task_id),
  )
  const completedCount = day.tasks.filter((task) => task.status === 'done').length
  const completedPlural = new Intl.PluralRules('ru-RU').select(completedCount)
  const completedLabel = `${taskCount(completedCount)} ${completedPlural === 'one' ? 'выполнена' : completedPlural === 'few' ? 'выполнены' : 'выполнено'}`
  const empty = day.slots.length === 0
  const withoutSlots = day.tasks.filter((task) => !taskIds.has(task.id))
  const unplaced = withoutSlots.filter(
    (task) => task.status !== 'done' && task.status !== 'skipped',
  )
  const finished = withoutSlots.filter(
    (task) => task.status === 'done' || task.status === 'skipped',
  )
  const firstCompleted = timeline.completed[0]
  const lastCompleted = timeline.completed.at(-1)
  const openTask = (task: Task) => onTaskSelect?.(task)

  return (
    <section className={styles.timeline} aria-labelledby={`${id}-heading`}>
      <header className={styles.header}>
        <div>
          <h2 id={`${id}-heading`} className="text-heading">
            План на день
          </h2>
          <p className={styles.subtitle}>
            {taskCount(day.tasks.length)} · {timelineDuration(timeline.scheduledMinutes)}{' '}
            запланировано
          </p>
        </div>
        <div className={styles.legend} aria-label="Обозначения на шкале">
          <span>
            <SparklesIcon size={14} /> поставлено алгоритмом
          </span>
          <span>
            <LockIcon size={14} /> закреплено
          </span>
          <span>
            <span className={styles.cycleKey} aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            окна по циклам
          </span>
        </div>
      </header>
      {firstCompleted && lastCompleted ? (
        <button
          className={styles.completed}
          type="button"
          aria-expanded={showCompleted}
          aria-controls={`${id}-scale`}
          onClick={() => setShowCompleted((current) => !current)}
        >
          <CheckIcon size={16} />
          <span>
            {completedLabel}
            {timeline.completed.length === completedCount
              ? ` · ${range(firstCompleted.start, lastCompleted.end)}`
              : ''}
          </span>
          <span className={styles.completedAction}>
            {showCompleted ? 'Скрыть' : 'Показать'} <ChevronDownIcon size={14} />
          </span>
        </button>
      ) : (
        <div className={styles.completed}>
          <CheckIcon size={16} />
          <span>{completedLabel}</span>
        </div>
      )}
      <div id={`${id}-scale`} className={styles.scale} style={{ height: timeline.height + 24 }}>
        <div className={styles.rail} aria-hidden="true" style={{ height: timeline.height }}>
          {timeline.rows.map(({ slot, task, top, height }) => (
            <span
              key={slot.id}
              className={styles.railSegment}
              data-type={task?.type ?? 'rest'}
              style={{ top, height }}
            />
          ))}
        </div>
        {timeline.ticks.map((tick) => (
          <div key={tick.at} className={styles.tick} style={{ top: tick.top }} aria-hidden="true">
            <span
              style={{
                visibility:
                  timeline.now && Math.abs(tick.top - timeline.now.top) < 20 ? 'hidden' : undefined,
              }}
            >
              {tick.label}
              {tick.offset ? <small>{tick.offset}</small> : null}
            </span>
            <span />
          </div>
        ))}
        {timeline.start < timeline.workStart ? (
          <div
            className={styles.outside}
            style={{ top: 0, height: timeline.position(timeline.workStart) }}
          >
            До рабочего окна · {clock(timeline.workStart)}
          </div>
        ) : null}
        {timeline.end > timeline.workEnd ? (
          <div
            className={styles.outside}
            style={{
              top: timeline.position(timeline.workEnd),
              height: timeline.position(timeline.end) - timeline.position(timeline.workEnd),
            }}
          >
            Вне рабочего окна · после {clock(timeline.workEnd)}
          </div>
        ) : null}
        {!empty
          ? timeline.gaps.map((gap) => {
              const label = `Свободно ${range(gap.start, gap.end)} · ${timelineDuration((gap.end - gap.start) / 60_000)}`
              const content = (
                <>
                  <PlusIcon size={16} />
                  <span>{label}</span>
                </>
              )
              const style = {
                top: timeline.position(gap.start) + 2,
                height: timeline.position(gap.end) - timeline.position(gap.start) - 4,
              }
              return onCreateTask ? (
                <button
                  key={gap.start}
                  type="button"
                  className={styles.free}
                  style={style}
                  aria-label={`Добавить задачу: ${label}`}
                  onClick={() => onCreateTask(day.date, clock(gap.start))}
                >
                  {content}
                </button>
              ) : (
                <div key={gap.start} className={styles.free} style={style}>
                  {content}
                </div>
              )
            })
          : null}
        <ol className={styles.slots} aria-label="Интервалы расписания">
          {timeline.rows.map(({ slot, task, start, end, duration, top, height }) => {
            const label = task
              ? task.title
              : SYSTEM_SLOT_LABELS[slot.kind as keyof typeof SYSTEM_SLOT_LABELS]
            const type = task?.type ?? 'rest'
            const state =
              task?.status === 'done'
                ? 'Выполнена'
                : task?.status === 'skipped'
                  ? 'Пропущена'
                  : slot.is_pinned
                    ? 'Время закреплено'
                    : 'Поставлена алгоритмом'
            const accessible = `${label}. ${range(start, end)}. ${timelineDuration(duration)}. ${task ? `${TASK_TYPES[task.type]}. ${state}.` : 'Системный интервал.'}`
            const Marker = task
              ? task.status === 'done'
                ? CheckIcon
                : slot.is_pinned
                  ? LockIcon
                  : SparklesIcon
              : slot.kind === 'rest'
                ? MoonIcon
                : slot.kind === 'lunch'
                  ? PlusIcon
                  : CoffeeIcon
            const content = (
              <>
                <div className={styles.cardContent}>
                  <span className={styles.cardTitle}>{label}</span>
                  <span className={styles.cardMeta}>
                    {range(start, end)} · {timelineDuration(duration)}
                    <span className={styles.cardType}>
                      {' '}
                      · {task ? TASK_TYPES[task.type].toLowerCase() : 'отдых'}
                    </span>
                  </span>
                </div>
                <Marker size={14} />
                {task && task.status !== 'done' && task.status !== 'skipped' ? (
                  <span className={styles.dragHint} aria-hidden="true">
                    <GripVerticalIcon size={16} />
                  </span>
                ) : null}
              </>
            )
            return (
              <li
                key={slot.id}
                className={styles.slot}
                style={{ top, height }}
                data-slot-id={slot.id}
                data-kind={slot.kind}
                data-type={type}
                data-status={task?.status}
                data-selected={(task && task.id === selectedTaskId) || undefined}
                data-size={
                  duration < 15
                    ? 'tiny'
                    : duration < 40
                      ? 'compact'
                      : duration < 80
                        ? 'regular'
                        : 'long'
                }
              >
                {task && onTaskSelect ? (
                  <button
                    type="button"
                    className={styles.card}
                    aria-label={accessible}
                    title={accessible}
                    data-task-edit-trigger
                    data-task-details-trigger
                    aria-haspopup="dialog"
                    aria-expanded={task.id === selectedTaskId}
                    onClick={() => openTask(task)}
                  >
                    {content}
                  </button>
                ) : (
                  <article className={styles.card} aria-label={accessible} title={accessible}>
                    {content}
                  </article>
                )}
              </li>
            )
          })}
        </ol>
        {empty ? (
          <div className={styles.empty} role="status">
            <CalendarIcon size={24} />
            <h3 className="text-heading">
              {unplaced.length
                ? 'Задачи пока не распределены'
                : finished.length
                  ? 'Нет запланированных интервалов'
                  : 'На этот день задач нет'}
            </h3>
            <p>
              {unplaced.length
                ? 'Задачи без времени показаны под шкалой.'
                : finished.length
                  ? 'Выполненные и пропущенные задачи показаны под шкалой.'
                  : 'Добавьте задачу — подберём для неё подходящее время в течение дня.'}
            </p>
            {onCreateTask ? (
              <Button className={styles.emptyAction} onClick={() => onCreateTask(day.date)}>
                <PlusIcon size={18} />
                Добавить задачу
              </Button>
            ) : null}
            <Button
              className={styles.emptyAction}
              variant="ghost"
              onClick={onImportCalendar}
              disabled={!onImportCalendar}
            >
              <LinkIcon size={18} />
              Импортировать из календаря
            </Button>
          </div>
        ) : null}
        {timeline.now ? (
          <div
            className={styles.now}
            style={{ top: timeline.now.top }}
            aria-label={`Сейчас ${timeline.now.label}`}
          >
            <span>{timeline.now.label}</span>
            <span />
          </div>
        ) : null}
      </div>
      <p className={styles.timezone}>Время расписания: {day.timezone}</p>
      <TaskDayList
        title="Без времени"
        tasks={unplaced}
        onTaskSelect={onTaskSelect}
        selectedTaskId={selectedTaskId}
      />
      <TaskDayList
        title="Выполненные и пропущенные"
        tasks={finished}
        onTaskSelect={onTaskSelect}
        selectedTaskId={selectedTaskId}
      />
      {!empty ? (
        <details className={styles.list}>
          <summary>Все интервалы списком</summary>
          <ol>
            {day.slots
              .slice()
              .sort((a, b) => Date.parse(a.start_at) - Date.parse(b.start_at))
              .map((slot) => {
                const task =
                  slot.kind === 'task'
                    ? day.tasks.find((item) => item.id === slot.task_id)
                    : undefined
                const label =
                  task?.title ?? SYSTEM_SLOT_LABELS[slot.kind as keyof typeof SYSTEM_SLOT_LABELS]
                return (
                  <li key={slot.id}>
                    <span>{range(Date.parse(slot.start_at), Date.parse(slot.end_at))}</span>
                    {task && onTaskSelect ? (
                      <button
                        type="button"
                        data-task-edit-trigger
                        data-task-details-trigger
                        aria-haspopup="dialog"
                        aria-expanded={task.id === selectedTaskId}
                        onClick={() => openTask(task)}
                      >
                        {label}
                      </button>
                    ) : (
                      <span>{label}</span>
                    )}
                  </li>
                )
              })}
          </ol>
        </details>
      ) : null}
    </section>
  )
}
