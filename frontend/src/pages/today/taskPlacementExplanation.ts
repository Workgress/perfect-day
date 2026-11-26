import type { ScheduleSlot, SchedulePlanningDetails } from '@/shared/model/schedule'
import type { Task } from '@/shared/model/task'
import { plannerExplanation } from '@/shared/lib/plannerText'
import { timelineClock } from './timelineModel'

export function taskPlacementExplanation(
  task: Task,
  slot: ScheduleSlot,
  timezone: string,
  planning?: SchedulePlanningDetails,
) {
  const saved = planning?.placement_explanations.find(
    (item) =>
      item.task_id === task.id &&
      item.planned_date === task.planned_date &&
      Date.parse(item.start_at) === Date.parse(slot.start_at) &&
      Date.parse(item.end_at) === Date.parse(slot.end_at),
  )
  const raw = saved?.explanation ?? slot.explanation
  const explanation = raw ? plannerExplanation(raw) : ''
  if (explanation) return explanation

  const start = timelineClock(Date.parse(slot.start_at), timezone)
  const end = timelineClock(Date.parse(slot.end_at), timezone)
  if (task.is_pinned || slot.is_pinned) return `Время ${start}–${end} закреплено вами.`
  if (task.actual_start) return 'Задача начата; время начала зафиксировано.'
  return `Задача запланирована на ${start}–${end}. Объяснение выбора времени пока недоступно.`
}
