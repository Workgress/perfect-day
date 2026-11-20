import { useId, useState } from 'react'
import { Link } from 'react-router'
import { editTaskPath, taskPath } from '@/app/router/paths'
import type { DailySchedule, SavedSchedule } from '@/shared/model/schedule'
import { TASK_TYPES, type TaskType } from '@/shared/model/task'
import { useCurrentTime } from '@/shared/lib/useCurrentTime'
import { localDate } from '@/shared/lib/dateTime'
import { Button } from '@/shared/ui/button/Button'
import {
  ArrowRightIcon,
  ChevronDownIcon,
  ClockIcon,
  InfoIcon,
  LockIcon,
  SparklesIcon,
} from '@/shared/ui/icon/icons'
import { timelineClock, timelineDuration } from './timelineModel'
import { useSessionStore } from '@/stores/session'
import { taskPlacementExplanation } from './taskPlacementExplanation'
import { todayLoad } from './todayLoadModel'
import { TodayLoadWarning } from './TodayLoadWarning'
import styles from './TodayDashboard.module.css'

export function TodayPlanSummary({
  day,
  warnings = [],
}: {
  day: DailySchedule
  warnings?: SavedSchedule['warnings']
}) {
  const now = useCurrentTime().getTime()
  const [loadExpanded, setLoadExpanded] = useState(false)
  const loadId = useId()
  const chronotype = useSessionStore((state) => state.user?.chronotype)
  const tasks = new Map(
    day.tasks.filter((task) => task.planned_date === day.date).map((task) => [task.id, task]),
  )
  const next = day.slots
    .filter(
      (slot) =>
        slot.kind === 'task' &&
        Date.parse(slot.end_at) > now &&
        tasks.get(slot.task_id)?.status === 'scheduled',
    )
    .sort((a, b) => Date.parse(a.start_at) - Date.parse(b.start_at))[0]
  const task = next?.kind === 'task' ? tasks.get(next.task_id) : undefined
  const explanation =
    task && next ? taskPlacementExplanation(task, next, day.timezone, chronotype) : null
  const remaining = next ? Math.max(0, Math.ceil((Date.parse(next.start_at) - now) / 60_000)) : 0
  const minutePlural = new Intl.PluralRules('ru-RU').select(remaining)
  const remainingLabel = `${remaining} ${minutePlural === 'one' ? 'минуту' : minutePlural === 'few' ? 'минуты' : 'минут'}`
  const deadline = task?.deadline ? new Date(task.deadline) : null
  const deadlineLabel = deadline
    ? localDate(deadline, day.timezone) === day.date
      ? timelineClock(deadline.getTime(), day.timezone)
      : new Intl.DateTimeFormat('ru-RU', {
          timeZone: day.timezone,
          day: '2-digit',
          month: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
        }).format(deadline)
    : null
  const load = todayLoad(day)
  const busy = load?.types ?? { intellectual: 0, physical: 0, creative: 0, routine: 0, rest: 0 }
  const scale = Math.max(load?.planned ?? 0, load?.capacity ?? 0, 1)
  const percent = load?.percent ?? null
  const reserve = load?.reserve ?? 0
  const hasUnplaced = day.unscheduled_task_ids.some((id) => {
    const task = tasks.get(id)
    return task?.planned_date === day.date && task.status === 'pending'
  })
  const overloaded =
    (percent !== null && percent > 85) ||
    hasUnplaced ||
    (warnings.some((warning) => warning.code === 'OVERLOAD') &&
      (!day.unscheduled_task_ids.length || hasUnplaced))
  const loadLabel =
    percent === null
      ? 'Нет запаса'
      : percent > 100
        ? 'Перегрузка'
        : overloaded
          ? 'Можно разгрузить день'
          : 'Комфортно'
  return (
    <aside className={styles.summary} aria-label="Сводка дня">
      <section
        className={styles.nextTask}
        aria-labelledby="today-next-task"
        style={task ? { boxShadow: `0 6px 32px var(--type-${task.type}-glow)` } : undefined}
      >
        <div className={styles.nextHeader}>
          <h2 id="today-next-task" className={styles.nextLabel}>
            {task
              ? remaining
                ? `Далее через ${remainingLabel}`
                : 'Сейчас по плану'
              : 'Ближайшая задача'}
          </h2>
          {task ? (
            <span
              className={styles.taskType}
              style={{ background: `var(--type-${task.type}-soft)` }}
            >
              <span style={{ background: `var(--type-${task.type})` }} aria-hidden="true" />
              {TASK_TYPES[task.type]}
            </span>
          ) : null}
        </div>
        {task && next ? (
          <>
            <Link className={styles.nextTitle} to={taskPath(task.id)}>
              {task.title}
            </Link>
            <p className={styles.nextMeta}>
              <span className={styles.nextTime}>
                {timelineClock(Date.parse(next.start_at), day.timezone)}–
                {timelineClock(Date.parse(next.end_at), day.timezone)}
              </span>
              <span>
                {(Date.parse(next.end_at) - Date.parse(next.start_at)) / 60_000} мин
                {deadlineLabel ? ` · дедлайн ${deadlineLabel}` : ''}
              </span>
            </p>
            {explanation ? (
              <p className={styles.explanation}>
                <SparklesIcon size={16} />
                {explanation}
              </p>
            ) : null}
            <div className={styles.nextActions}>
              <Button size="s" variant="secondary" disabled title="Запуск задачи пока недоступен">
                <ArrowRightIcon />
                Начать
              </Button>
              <Link to={editTaskPath(task.id)}>
                <ClockIcon size={16} />
                Перенести
              </Link>
              <Button size="s" variant="ghost" disabled title="Закрепление времени пока недоступно">
                <LockIcon />
                Закрепить
              </Button>
            </div>
          </>
        ) : (
          <p className={styles.context}>На сегодня больше нет запланированных задач.</p>
        )}
      </section>
      <section
        className={styles.load}
        data-overloaded={overloaded || undefined}
        aria-labelledby="today-load"
      >
        {load ? (
          <>
            <h2 id="today-load">
              <button
                className={styles.loadToggle}
                type="button"
                aria-expanded={loadExpanded}
                aria-controls={loadId}
                onClick={() => setLoadExpanded((value) => !value)}
              >
                <span>Нагрузка</span>
                {!loadExpanded ? (
                  <span className={styles.loadCompact}>
                    {timelineDuration(load.planned)} из {timelineDuration(load.capacity)}
                  </span>
                ) : null}
                <span className={styles.loadBadge} data-level={overloaded ? 'warning' : 'normal'}>
                  {loadLabel}
                </span>
                <ChevronDownIcon size={16} />
              </button>
            </h2>
            {loadExpanded ? (
              <p className={styles.loadValue}>
                <strong>{timelineDuration(load.planned)}</strong>
                <span>
                  из {timelineDuration(load.capacity)} рабочего окна ·{' '}
                  {reserve >= 0
                    ? `запас ${timelineDuration(reserve)}`
                    : `сверх плана ${timelineDuration(-reserve)}`}
                </span>
              </p>
            ) : null}
            <div
              className={styles.loadBar}
              role="img"
              aria-label={`Нагрузка: ${load.planned} из ${load.capacity} минут, ${percent} %`}
            >
              {Object.entries(busy).map(([type, minutes]) => (
                <span
                  key={type}
                  style={{
                    width: `${(minutes / scale) * 100}%`,
                    background: `var(--type-${type})`,
                  }}
                />
              ))}
            </div>
            <div id={loadId} hidden={!loadExpanded}>
              <ul className={styles.loadLegend} aria-label="Нагрузка по типам задач">
                {Object.entries(busy)
                  .filter(([, minutes]) => minutes > 0)
                  .map(([type, minutes]) => (
                    <li key={type}>
                      <span
                        className={styles.loadSwatch}
                        style={{ background: `var(--type-${type})` }}
                        aria-hidden="true"
                      />
                      {type === 'rest' ? 'Отдых' : TASK_TYPES[type as TaskType]}{' '}
                      {timelineDuration(minutes)}
                    </li>
                  ))}
              </ul>
              <p className={styles.loadNote}>
                <InfoIcon size={14} />
                <span>Загрузка показывает долю задач в рабочем окне.</span>
              </p>
            </div>
            {overloaded ? <TodayLoadWarning day={day} now={now} /> : null}
          </>
        ) : (
          <p className={styles.context}>Не удалось определить рабочее окно.</p>
        )}
      </section>
    </aside>
  )
}
