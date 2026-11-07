import type { PlanPreview, PlanPreviewRequest } from '@/shared/model/plan'
import { http } from './http'

export async function previewPlan(
  body: PlanPreviewRequest,
  signal?: AbortSignal,
): Promise<PlanPreview> {
  const result = await http<PlanPreview>('/onboarding/preview', { method: 'POST', body, signal })
  const indexes = new Set<number>()
  const validIndex = (index: number) =>
    Number.isInteger(index) && index >= 0 && index < body.tasks.length && !indexes.has(index)
  const validTime = (value: string) => /^([01]\d|2[0-3]):[0-5]\d:00$/.test(value)
  const minutes = (value: string) => Number(value.slice(0, 2)) * 60 + Number(value.slice(3, 5))
  if (
    !result ||
    result.planned_date !== body.planned_date ||
    typeof result.timezone !== 'string' ||
    !Array.isArray(result.slots) ||
    !Array.isArray(result.unscheduled_task_indexes)
  )
    throw new Error('Не удалось прочитать предпросмотр плана.')
  new Intl.DateTimeFormat('ru', { timeZone: result.timezone })
  let previousEnd = '00:00:00'
  for (const slot of result.slots) {
    if (
      !slot ||
      !validIndex(slot.task_index) ||
      !validTime(slot.start_time) ||
      !validTime(slot.end_time) ||
      slot.end_time <= slot.start_time ||
      slot.start_time < previousEnd ||
      minutes(slot.end_time) - minutes(slot.start_time) !==
        body.tasks[slot.task_index].duration_min ||
      typeof slot.explanation !== 'string' ||
      !slot.explanation.trim()
    )
      throw new Error('Сервер вернул некорректный предпросмотр плана.')
    previousEnd = slot.end_time
    indexes.add(slot.task_index)
  }
  for (const index of result.unscheduled_task_indexes) {
    if (!validIndex(index)) throw new Error('Сервер вернул некорректный список задач.')
    indexes.add(index)
  }
  if (indexes.size !== body.tasks.length)
    throw new Error('В предпросмотре отсутствуют некоторые задачи.')
  return result
}
