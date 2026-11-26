import { resolveLocalDateTime } from '@/shared/lib/dateTime'
import type { DailySchedule } from '@/shared/model/schedule'

export function transferProposals(day: DailySchedule, now: number) {
  const start = resolveLocalDateTime(`${day.date}T${day.work_start.slice(0, 5)}`, day.timezone)
  const end = resolveLocalDateTime(`${day.date}T${day.work_end.slice(0, 5)}`, day.timezone)
  if (start.status !== 'valid' || end.status !== 'valid') return []
  return (day.planning?.recommendations ?? []).flatMap((recommendation) => {
    const task = day.tasks.find((item) => item.id === recommendation.task_id)
    if (
      !task ||
      task.planned_date !== day.date ||
      recommendation.from_date !== day.date ||
      task.is_pinned ||
      task.is_date_locked ||
      task.actual_start ||
      !['pending', 'scheduled'].includes(task.status)
    )
      return []
    const slots = day.slots.filter((slot) => slot.kind === 'task' && slot.task_id === task.id)
    if (slots.some((slot) => Date.parse(slot.start_at) <= now)) return []
    const released = slots.reduce(
      (sum, slot) =>
        sum +
        Math.max(
          0,
          Math.min(Date.parse(slot.end_at), end.instant) -
            Math.max(Date.parse(slot.start_at), start.instant),
        ) /
          60_000,
      0,
    )
    return [
      {
        task,
        date: recommendation.to_date,
        released,
        explanation: recommendation.explanation,
        key: `${task.id}:${task.version}:${recommendation.to_date}:${day.schedule?.version}`,
      },
    ]
  })
}

export function transferProposal(day: DailySchedule, now: number) {
  return transferProposals(day, now)[0] ?? null
}
