import { addDays } from '@/pages/biorhythms/biorhythmChartModel'
import { resolveLocalDateTime } from '@/shared/lib/dateTime'
import type { DailySchedule } from '@/shared/model/schedule'

export function transferProposal(day: DailySchedule, now: number) {
  const date = addDays(day.date, 1)
  const targetStart = resolveLocalDateTime(`${date}T${day.work_start.slice(0, 5)}`, day.timezone)
  const targetEnd = resolveLocalDateTime(`${date}T${day.work_end.slice(0, 5)}`, day.timezone)
  const sourceStart = resolveLocalDateTime(
    `${day.date}T${day.work_start.slice(0, 5)}`,
    day.timezone,
  )
  const sourceEnd = resolveLocalDateTime(`${day.date}T${day.work_end.slice(0, 5)}`, day.timezone)
  if (
    targetStart.status !== 'valid' ||
    targetEnd.status !== 'valid' ||
    sourceStart.status !== 'valid' ||
    sourceEnd.status !== 'valid'
  )
    return null
  const priority = { low: 0, medium: 1, high: 2 }
  const candidates = day.tasks
    .filter((task) => {
      if (
        task.planned_date !== day.date ||
        task.type === 'routine' ||
        task.is_pinned ||
        (task.status !== 'scheduled' && task.status !== 'pending')
      )
        return false
      const end = targetStart.instant + task.duration_min * 60_000
      if (end > targetEnd.instant || (task.deadline && Date.parse(task.deadline) < end))
        return false
      if (task.status === 'pending') return true
      return day.slots.some(
        (slot) =>
          slot.kind === 'task' && slot.task_id === task.id && Date.parse(slot.start_at) > now,
      )
    })
    .sort(
      (a, b) =>
        Number(a.status !== 'pending') - Number(b.status !== 'pending') ||
        priority[a.priority] - priority[b.priority] ||
        b.duration_min - a.duration_min ||
        a.id.localeCompare(b.id),
    )
  const task = candidates[0]
  if (!task) return null
  const released = day.slots
    .filter((slot) => slot.kind === 'task' && slot.task_id === task.id)
    .reduce(
      (sum, slot) =>
        sum +
        Math.max(
          0,
          Math.min(Date.parse(slot.end_at), sourceEnd.instant) -
            Math.max(Date.parse(slot.start_at), sourceStart.instant),
        ) /
          60_000,
      0,
    )
  return {
    task,
    date,
    released,
    key: `${task.id}:${task.version}:${date}:${day.schedule?.version}`,
  }
}
