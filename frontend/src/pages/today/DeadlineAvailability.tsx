import { useQuery } from '@tanstack/react-query'
import { getSchedule } from '@/shared/api/schedule'
import { apiProblem } from '@/shared/api/errors'
import { isCalendarDate, resolveLocalDateTime } from '@/shared/lib/dateTime'
import { useSessionStore } from '@/stores/session'
import type { SavedSchedule } from '@/shared/model/schedule'
import type { TaskFormContext } from './taskFormModel'
import { nextTaskDays } from './taskTimeOptions'
import { taskSessionRequest } from './taskSessionRequest'
import styles from './DeadlineAvailability.module.css'

export function hasDeadlineWindow(
  days: { date: string; schedule: SavedSchedule | null }[],
  context: TaskFormContext,
  duration: number,
  deadline: number,
  now: number,
) {
  return days.some(({ date, schedule }) => {
    const open = resolveLocalDateTime(`${date}T${context.workStart}`, context.timezone)
    const close = resolveLocalDateTime(`${date}T${context.workEnd}`, context.timezone)
    if (open.status !== 'valid' || close.status !== 'valid') return true // Unknown must not become a false warning.
    let cursor = Math.max(open.instant, now)
    const end = Math.min(close.instant, deadline)
    const occupied = (schedule?.slots ?? [])
      .filter((slot) => slot.kind !== 'lunch')
      .sort((a, b) => Date.parse(a.start_at) - Date.parse(b.start_at))
    for (const slot of occupied) {
      const start = Date.parse(slot.start_at)
      if (Math.min(start, end) - cursor >= duration * 60_000) return true
      cursor = Math.max(cursor, Date.parse(slot.end_at))
      if (cursor >= end) return false
    }
    return end - cursor >= duration * 60_000
  })
}

export function DeadlineAvailability({
  context,
  date,
  duration,
  deadline,
  now,
}: {
  context: TaskFormContext
  date: string
  duration: number
  deadline: string
  now: Date
}) {
  const generation = useSessionStore((state) => state.generation)
  const limit = resolveLocalDateTime(deadline, context.timezone)
  const dates = nextTaskDays(date, 31).filter((day) => day <= deadline.slice(0, 10))
  const complete = isCalendarDate(date) && dates.at(-1) === deadline.slice(0, 10)
  const query = useQuery({
    queryKey: ['deadline-availability', generation, dates, context.timezone],
    enabled: complete && limit.status === 'valid',
    retry: false,
    staleTime: 15_000,
    queryFn: ({ signal }) =>
      taskSessionRequest(
        generation,
        async (requestSignal) => {
          const days: { date: string; schedule: SavedSchedule | null }[] = []
          for (let i = 0; i < dates.length; i += 4) {
            days.push(
              ...(await Promise.all(
                dates.slice(i, i + 4).map(async (day) => {
                  try {
                    const schedule = await getSchedule(day, requestSignal)
                    if (schedule.timezone !== context.timezone)
                      throw new Error('Часовой пояс изменился')
                    return { date: day, schedule }
                  } catch (error) {
                    if (apiProblem(error)?.code === 'SCHEDULE_NOT_FOUND')
                      return { date: day, schedule: null }
                    throw error
                  }
                }),
              )),
            )
          }
          return days
        },
        signal,
      ),
  })
  if (
    !complete ||
    limit.status !== 'valid' ||
    !query.isSuccess ||
    query.isFetching ||
    hasDeadlineWindow(query.data, context, duration, limit.instant, now.getTime())
  )
    return null
  return (
    <section className={styles.warning} role="status" aria-label="Проверка срока">
      <h3>Нет свободного окна</h3>
      <p>
        До указанного срока нет свободного окна на {duration} мин. Уточните срок или длительность.
      </p>
      <p>
        При сохранении планировщик проверит возможность сдвинуть незакреплённые задачи. Если задача
        не поместится, она останется без времени.
      </p>
    </section>
  )
}
