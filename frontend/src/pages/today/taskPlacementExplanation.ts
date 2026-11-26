import type { ScheduleSlot } from '@/shared/model/schedule'
import type { Task } from '@/shared/model/task'
import { plannerExplanation } from '@/shared/lib/plannerText'
import { timelineClock } from './timelineModel'

export function taskPlacementExplanation(task: Task, slot: ScheduleSlot, timezone: string) {
  const explanation = slot.explanation ? plannerExplanation(slot.explanation) : ''
  if (explanation) return explanation

  const start = timelineClock(Date.parse(slot.start_at), timezone)
  const end = timelineClock(Date.parse(slot.end_at), timezone)
  if (task.is_pinned || slot.is_pinned) return `Время ${start}–${end} закреплено вами.`
  if (task.actual_start) return 'Задача начата; время начала зафиксировано.'
  return `Задача запланирована на ${start}–${end}. Объяснение выбора времени пока недоступно.`
}
