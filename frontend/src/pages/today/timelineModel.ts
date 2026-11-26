import { localDate, resolveLocalDateTime } from '@/shared/lib/dateTime'
import type { DailySchedule, ScheduleSlot } from '@/shared/model/schedule'
import type { Task } from '@/shared/model/task'

export const TIMELINE_PIXELS_PER_MINUTE = 72 / 60
const MINUTE = 60_000

export function timelineClock(instant: number, timezone: string) {
  return new Intl.DateTimeFormat('ru-RU', {
    timeZone: timezone,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(new Date(instant))
}

export function timelineDuration(minutes: number) {
  const hours = Math.floor(minutes / 60)
  const rest = Math.round(minutes % 60)
  return hours ? `${hours} ч${rest ? ` ${rest} мин` : ''}` : `${rest} мин`
}

function localInstant(date: string, clock: string, timezone: string) {
  const result = resolveLocalDateTime(`${date}T${clock.slice(0, 5)}`, timezone)
  if (result.status !== 'valid')
    throw new Error('Не удалось отобразить рабочее время в часовом поясе расписания.')
  return result.instant
}

export function buildTimeline(day: DailySchedule, showCompleted: boolean, now: Date) {
  const nowAt = now.getTime()
  const isToday = localDate(now, day.timezone) === day.date
  const workStart = localInstant(day.date, day.work_start, day.timezone)
  const workEnd = localInstant(day.date, day.work_end, day.timezone)
  if (workEnd <= workStart) throw new Error('Окончание рабочего дня должно быть позже начала.')
  const taskMap = new Map(day.tasks.map((task) => [task.id, task]))
  const slots = day.slots
    .map((slot) => {
      const start = Date.parse(slot.start_at)
      const end = Date.parse(slot.end_at)
      const task = slot.kind === 'task' ? taskMap.get(slot.task_id) : undefined
      if (
        !Number.isFinite(start) ||
        !Number.isFinite(end) ||
        end <= start ||
        (slot.kind === 'task' && !task)
      )
        throw new Error('В расписании есть некорректный интервал. Обновите данные дня.')
      return { slot, start, end, task, duration: (end - start) / MINUTE }
    })
    .sort((a, b) => a.start - b.start || a.end - b.end)

  const completed = [] as typeof slots
  for (const slot of slots) {
    if (
      slot.task?.status !== 'done' ||
      slot.end > now.getTime() ||
      (completed.length && slot.start !== completed.at(-1)!.end)
    )
      break
    completed.push(slot)
  }
  const hiddenIds = new Set(showCompleted ? [] : completed.map((item) => item.slot.id))
  const visible = slots.filter((item) => !hiddenIds.has(item.slot.id))
  const collapsedStart = completed.at(-1)?.end ?? workStart
  const start = Math.min(
    showCompleted ? workStart : Math.max(workStart, collapsedStart),
    ...visible.map((item) => item.start),
    isToday ? nowAt : Infinity,
  )
  const nextDate = new Date(Date.parse(`${day.date}T12:00:00Z`) + 86_400_000)
    .toISOString()
    .slice(0, 10)
  const dayEnd = localInstant(nextDate, '00:00', day.timezone)
  const end = Math.max(
    Math.min(workEnd + 60 * MINUTE, dayEnd),
    ...visible.map((item) => item.end),
    isToday ? Math.min(nowAt + MINUTE, dayEnd) : -Infinity,
  )
  const position = (at: number) => ((at - start) / MINUTE) * TIMELINE_PIXELS_PER_MINUTE
  const ticks: { at: number; label: string; offset: string | null; top: number }[] = []
  const minutePart = Number(
    new Intl.DateTimeFormat('en', { timeZone: day.timezone, minute: '2-digit' }).format(
      new Date(start),
    ),
  )
  let tick = start
  while (tick <= end) {
    ticks.push({
      at: tick,
      label: timelineClock(tick, day.timezone),
      offset: null,
      top: position(tick),
    })
    tick += (tick === start && minutePart ? 60 - minutePart : 60) * MINUTE
  }
  if (ticks.at(-1)?.at !== end)
    ticks.push({
      at: end,
      label: timelineClock(end, day.timezone),
      offset: null,
      top: position(end),
    })
  for (const row of visible) {
    if (ticks.every((item) => Math.abs(item.top - position(row.start)) >= 20))
      ticks.push({
        at: row.start,
        label: timelineClock(row.start, day.timezone),
        offset: null,
        top: position(row.start),
      })
  }
  ticks.sort((a, b) => a.at - b.at)
  const counts = new Map<string, number>()
  ticks.forEach((item) => counts.set(item.label, (counts.get(item.label) ?? 0) + 1))
  ticks.forEach((item) => {
    if (counts.get(item.label)! > 1)
      item.offset = new Intl.DateTimeFormat('en', {
        timeZone: day.timezone,
        timeZoneName: 'shortOffset',
      })
        .formatToParts(new Date(item.at))
        .find((part) => part.type === 'timeZoneName')!.value
  })
  const gaps: { start: number; end: number }[] = []
  let cursor = Math.max(start, workStart)
  for (const slot of visible) {
    const boundary = Math.min(slot.start, workEnd)
    if (boundary - cursor >= 60 * MINUTE) gaps.push({ start: cursor, end: boundary })
    cursor = Math.max(cursor, slot.end)
  }
  if (workEnd - cursor >= 60 * MINUTE) gaps.push({ start: cursor, end: workEnd })
  const unscheduled = [...new Set(day.unscheduled_task_ids)]
    .map((id) => taskMap.get(id))
    .filter((task): task is Task =>
      Boolean(
        task &&
        task.status !== 'done' &&
        task.status !== 'skipped' &&
        !slots.some((item) => item.task?.id === task.id),
      ),
    )
  const scheduledMinutes = slots.reduce(
    (sum, item) => sum + (item.task && item.task.status !== 'skipped' ? item.duration : 0),
    0,
  )
  return {
    start,
    end,
    workStart,
    workEnd,
    position,
    ticks,
    gaps,
    completed,
    unscheduled,
    scheduledMinutes,
    rows: visible.map((item) => ({
      ...item,
      top: position(item.start),
      height: item.duration * TIMELINE_PIXELS_PER_MINUTE,
    })),
    height: position(end),
    now:
      isToday && nowAt >= start && nowAt <= end
        ? { top: position(nowAt), label: timelineClock(nowAt, day.timezone) }
        : null,
  }
}

export const SYSTEM_SLOT_LABELS: Record<Exclude<ScheduleSlot['kind'], 'task'>, string> = {
  break: 'Перерыв, прогулка',
  lunch: 'Обед',
  rest: 'Отдых',
  history: 'Удалённая задача',
}
