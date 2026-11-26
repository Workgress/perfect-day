import { apiProblem } from '@/shared/api/errors'
import { getSchedule } from '@/shared/api/schedule'
import { getTask, pinTask } from '@/shared/api/tasks'
import type { Task } from '@/shared/model/task'

/** Finish creation with a separate placement command; retries never create another task. */
export async function pinNewTask(
  id: string,
  date: string,
  start: string,
  timezone: string,
  signal: AbortSignal,
) {
  const readSchedule = async (day: string) => {
    try {
      const saved = await getSchedule(day, signal)
      signal.throwIfAborted()
      if (saved.timezone !== timezone)
        throw new Error('Часовой пояс расписания изменился. Обновите страницу.')
      return saved
    } catch (error) {
      if (apiProblem(error)?.code === 'SCHEDULE_NOT_FOUND') return null
      throw error
    }
  }
  const matches = (task: Task) =>
    task.is_pinned &&
    task.planned_date === date &&
    task.pinned_start !== null &&
    Date.parse(task.pinned_start) === Date.parse(start)
  const confirmed = async (task: Task) => {
    if (!matches(task)) return false
    const saved = await readSchedule(date)
    return saved?.slots.some(
      (slot) =>
        slot.task_id === id &&
        slot.is_pinned &&
        Date.parse(slot.start_at) === Date.parse(start) &&
        Date.parse(slot.end_at) - Date.parse(slot.start_at) === task.duration_min * 60_000,
    )
  }
  const task = await getTask(id, signal)
  signal.throwIfAborted()
  if (await confirmed(task)) return task
  const source = await readSchedule(task.planned_date)
  const versions = { [task.planned_date]: source?.version ?? 0 }
  if (date !== task.planned_date) versions[date] = (await readSchedule(date))?.version ?? 0
  signal.throwIfAborted()
  try {
    const pinned = await pinTask(
      id,
      {
        planned_date: date,
        start_at: start,
        version: task.version,
        schedule_versions: versions,
      },
      signal,
    )
    if (!matches(pinned)) throw new Error('Сервер не подтвердил выбранное время задачи.')
    return pinned
  } catch (error) {
    signal.throwIfAborted()
    // A lost response may still mean the pin was committed. Confirm it without replaying POST.
    try {
      const fresh = await getTask(id, signal)
      if (await confirmed(fresh)) return fresh
    } catch {
      signal.throwIfAborted()
    }
    throw error
  }
}
