import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { DailySchedule } from '@/shared/model/schedule'
import { taskKeys } from '@/shared/api/planningKeys'
import { useSessionStore } from '@/stores/session'
import { CheckIcon, SunIcon } from '@/shared/ui/icon/icons'
import { addDays } from '@/pages/biorhythms/biorhythmChartModel'
import { getDayTasks } from './useTodaySchedule'
import { taskSessionRequest } from './taskSessionRequest'
import { useTodayBiorhythms } from './useTodayBiorhythms'
import { timelineDuration } from './timelineModel'
import styles from './TodayDayEnd.module.css'

export function TodayDayEnd({ day }: { day: DailySchedule }) {
  const owner = useSessionStore((state) => state.ownerId)
  const generation = useSessionStore((state) => state.generation)
  const key = `perfect-day:feeling:${owner ?? generation}:${day.date}`
  return <DayEndContent key={key} day={day} storageKey={key} generation={generation} />
}

function DayEndContent({
  day,
  storageKey,
  generation,
}: {
  day: DailySchedule
  storageKey: string
  generation: number
}) {
  const [rating, setRating] = useState<number | null>(() => {
    try {
      const value = Number(localStorage.getItem(storageKey))
      return value >= 1 && value <= 5 ? value : null
    } catch {
      return null
    }
  })
  const [saved, setSaved] = useState(false)
  const tomorrow = addDays(day.date, 1)
  const rhythms = useTodayBiorhythms(day.date)
  const tomorrowTasks = useQuery({
    queryKey: taskKeys.day(generation, tomorrow),
    queryFn: ({ signal }) =>
      taskSessionRequest(
        generation,
        (requestSignal) => getDayTasks(tomorrow, requestSignal),
        signal,
      ),
    retry: false,
  })
  const tasks = day.tasks
  const done = tasks.filter((task) => task.planned_date === day.date && task.status === 'done')
  const moved = new Set([
    ...tasks.filter((task) => task.planned_date !== day.date).map((task) => task.id),
    ...(day.planning?.schedule.moves.filter((move) => move.from_date === day.date && move.to_date !== day.date).map((move) => move.task_id) ?? []),
  ])
  const total = new Set([...tasks.map((task) => task.id), ...moved]).size
  const pending = tasks.filter(
    (task) => task.planned_date === day.date && !['done', 'skipped'].includes(task.status),
  )
  const skipped = tasks.filter((task) => task.planned_date === day.date && task.status === 'skipped')
  const reading = !rhythms.isError
    ? rhythms.data?.series.points.find((point) => point.date === tomorrow)
    : undefined
  const dateLabel = new Intl.DateTimeFormat('ru-RU', {
    timeZone: 'UTC',
    weekday: 'short',
    day: 'numeric',
    month: 'long',
  }).format(new Date(`${tomorrow}T12:00:00Z`))
  const percent = (value: number) => `${value > 0 ? '+' : ''}${Math.round(value)} %`
  return (
    <section className={styles.card} aria-label="Итог дня">
      <h2 className={styles.label}>
        <CheckIcon size={18} />
        День завершён
      </h2>
      <p className={styles.total}>
        <strong>
          {done.length} из {total}
        </strong>
        <span>
          задач · {timelineDuration(done.reduce((sum, task) => sum + task.duration_min, 0))} работы
        </span>
      </p>
      <p className={styles.description}>
        {pending.length
          ? `Без выполнения: ${pending.length}. Их можно открыть в плане и перенести.`
          : 'Все задачи на сегодня разобраны.'}
        {skipped.length ? ` Пропущено: ${skipped.length}.` : ''}
        {moved.size ? ` Перенесено на другие дни: ${moved.size}.` : ''}
      </p>
      <fieldset className={styles.feeling}>
        <legend>Как вы себя чувствуете?</legend>
        <div className={styles.ratings}>
          {[1, 2, 3, 4, 5].map((value) => (
            <label key={value} data-selected={rating === value || undefined}>
              <input
                type="radio"
                name="day-feeling"
                value={value}
                checked={rating === value}
                aria-label={`${value} из 5`}
                onChange={() => {
                  setRating(value)
                  try {
                    localStorage.setItem(storageKey, String(value))
                    setSaved(true)
                  } catch {
                    setSaved(false)
                  }
                }}
              />
              {value}
            </label>
          ))}
        </div>
        <div className={styles.scale}>
          <span>устал</span>
          <span>полон сил</span>
        </div>
        <p className={styles.note} role="status">
          {saved ? 'Сохранено на этом устройстве.' : 'Оценка хранится только на этом устройстве.'}
        </p>
      </fieldset>
      <div className={styles.tomorrow}>
        <SunIcon size={18} />
        <div>
          <h3>Завтра, {dateLabel}</h3>
          {reading ? (
            <p>
              Интеллектуальный {percent(reading.cycles.intellectual.percent)}, физический{' '}
              {percent(reading.cycles.physical.percent)}.
            </p>
          ) : null}
          <p>
            {tomorrowTasks.isPending
              ? 'Загружаем задачи на завтра…'
              : tomorrowTasks.isError
                ? 'Не удалось загрузить задачи на завтра.'
                : `Задач в плане: ${tomorrowTasks.data?.length ?? 0}.`}
          </p>
        </div>
      </div>
    </section>
  )
}
