import { resolveLocalDateTime } from '@/shared/lib/dateTime'
import type { DailySchedule } from '@/shared/model/schedule'
import type { TaskType } from '@/shared/model/task'

export function todayLoad(day: DailySchedule) {
  const start = resolveLocalDateTime(`${day.date}T${day.work_start.slice(0, 5)}`, day.timezone)
  const end = resolveLocalDateTime(`${day.date}T${day.work_end.slice(0, 5)}`, day.timezone)
  if (start.status !== 'valid' || end.status !== 'valid' || end.instant <= start.instant)
    return null
  const types: Record<TaskType | 'rest', number> = {
    intellectual: 0,
    physical: 0,
    creative: 0,
    routine: 0,
    rest: 0,
  }
  const tasks = new Map(
    day.tasks.filter((task) => task.planned_date === day.date).map((task) => [task.id, task]),
  )
  for (const slot of day.slots) {
    const task = slot.kind === 'task' ? tasks.get(slot.task_id) : undefined
    if (slot.kind === 'task' && (!task || task.status === 'skipped')) continue
    const type = task?.type ?? (slot.kind === 'lunch' ? 'routine' : 'rest')
    types[type] +=
      Math.max(
        0,
        Math.min(Date.parse(slot.end_at), end.instant) -
          Math.max(Date.parse(slot.start_at), start.instant),
      ) / 60_000
  }
  const planned = Object.values(types).reduce((sum, minutes) => sum + minutes, 0)
  const capacity = (end.instant - start.instant) / 60_000
  return {
    types,
    planned,
    capacity,
    reserve: capacity - planned,
    percent: Math.round((planned / capacity) * 100),
  }
}
