import type { DailySchedule, SavedSchedule } from '@/shared/model/schedule'
import type { Task } from '@/shared/model/task'

/** Work clocks must belong to the saved timezone, not the browser timezone. */
export function dailySchedule(
  saved: SavedSchedule,
  tasks: Task[],
  work: { timezone: string; work_start: string; work_end: string },
): DailySchedule {
  if (work.timezone !== saved.timezone)
    throw new Error('Рабочее время задано в другом часовом поясе, чем сохранённое расписание.')
  const referenced = new Set([
    ...saved.slots.flatMap((slot) => (slot.task_id === null ? [] : [slot.task_id])),
    ...saved.unscheduled.map((item) => item.task_id),
  ])
  const available = new Set(tasks.map((task) => task.id))
  if ([...referenced].some((id) => !available.has(id)))
    throw new Error('Загрузите все задачи, на которые ссылается расписание.')
  return {
    date: saved.planned_date,
    timezone: saved.timezone,
    work_start: work.work_start,
    work_end: work.work_end,
    schedule: { id: saved.id, version: saved.version },
    tasks: tasks.filter(
      (task) => task.planned_date === saved.planned_date || referenced.has(task.id),
    ),
    slots: [...saved.slots],
    unscheduled_task_ids: saved.unscheduled.map((item) => item.task_id),
  }
}
