import {
  isCalendarDate,
  localDate,
  localDateTime,
  resolveLocalDateTime,
} from '@/shared/lib/dateTime'
import type { BiorhythmSeries } from '@/shared/model/biorhythm'
import type { SavedSchedule } from '@/shared/model/schedule'
import type { TaskType } from '@/shared/model/task'

export type TaskTimeOption = {
  start: string
  end: string
  date: string
  explanation: string
  score: number
}

export function nextTaskDays(date: string, count = 7) {
  const first = Date.parse(`${date}T12:00:00Z`)
  if (!Number.isFinite(first) || !isCalendarDate(date)) return []
  return Array.from({ length: count }, (_, index) =>
    new Date(first + index * 86_400_000).toISOString().slice(0, 10),
  ).filter(isCalendarDate)
}

export function taskTimeOptions({
  days,
  rhythms,
  timezone,
  workStart,
  workEnd,
  duration,
  type,
  now,
  deadline,
}: {
  days: { date: string; schedule: SavedSchedule | null }[]
  rhythms?: BiorhythmSeries
  timezone: string
  workStart: string
  workEnd: string
  duration: number | ''
  type: TaskType | ''
  now: Date
  deadline: string
}): TaskTimeOption[] {
  if (!Number.isInteger(duration) || Number(duration) < 5 || Number(duration) > 480 || !type)
    return []
  const limit = deadline ? resolveLocalDateTime(deadline, timezone) : null
  if (limit && limit.status !== 'valid') return []
  const points = rhythms?.timezone === timezone ? rhythms.points : []
  const candidates: TaskTimeOption[] = []
  for (const { date, schedule } of days) {
    if (schedule && schedule.timezone !== timezone) continue
    const open = resolveLocalDateTime(`${date}T${workStart}`, timezone)
    const close = resolveLocalDateTime(`${date}T${workEnd}`, timezone)
    if (open.status !== 'valid' || close.status !== 'valid') continue
    const starts = new Set<number>()
    for (
      let start = open.instant;
      start + Number(duration) * 60_000 <= close.instant;
      start += 30 * 60_000
    )
      starts.add(start)
    for (const slot of schedule?.slots ?? []) starts.add(Date.parse(slot.end_at))
    for (const start of starts) {
      const end = start + Number(duration) * 60_000
      if (start < open.instant || end > close.instant) continue
      if (start <= now.getTime() || (limit?.status === 'valid' && end > limit.instant)) continue
      if (
        resolveLocalDateTime(localDateTime(new Date(start), timezone), timezone).status !== 'valid'
      )
        continue
      if (
        schedule?.slots.some(
          (slot) => start < Date.parse(slot.end_at) && end > Date.parse(slot.start_at),
        )
      )
        continue
      const midpoint = (start + end) / 2
      const point = points
        .filter((item) => item.date === date)
        .reduce<(typeof points)[number] | undefined>(
          (nearest, item) =>
            !nearest ||
            Math.abs(Date.parse(item.at) - midpoint) < Math.abs(Date.parse(nearest.at) - midpoint)
              ? item
              : nearest,
          undefined,
        )
      const cycle = type === 'creative' ? 'emotional' : type === 'routine' ? null : type
      const reading = cycle && point ? point.cycles[cycle] : null
      const score = reading
        ? reading.percent - point!.critical.level * 15
        : type === 'routine' && point
          ? -Math.max(...Object.values(point.cycles).map((item) => item.percent))
          : 0
      const name =
        cycle === 'emotional'
          ? 'Эмоциональный'
          : cycle === 'physical'
            ? 'Физический'
            : 'Интеллектуальный'
      candidates.push({
        date,
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
        score,
        explanation: reading
          ? `${name} цикл ${Math.round(reading.percent)} %${point!.critical.level ? ' · критический день' : ''}`
          : 'Свободное окно в рабочем дне',
      })
    }
  }
  candidates.sort((a, b) => b.score - a.score || Date.parse(a.start) - Date.parse(b.start))
  // Offer different days and non-overlapping alternatives rather than four near-identical starts.
  const selected: TaskTimeOption[] = []
  for (const maxPerDay of [1, 2]) {
    for (const option of candidates) {
      if (selected.length === 4) break
      if (selected.filter((item) => item.date === option.date).length >= maxPerDay) continue
      if (
        selected.some(
          (item) =>
            Date.parse(option.start) < Date.parse(item.end) &&
            Date.parse(option.end) > Date.parse(item.start),
        )
      )
        continue
      selected.push(option)
    }
  }
  return selected.sort((a, b) => b.score - a.score || Date.parse(a.start) - Date.parse(b.start))
}

export function taskTimeLabel(start: string, end: string, timezone: string, now: Date) {
  const date = localDate(new Date(start), timezone)
  const today = localDate(now, timezone)
  const day =
    date === today
      ? 'Сегодня'
      : date === nextTaskDays(today, 2)[1]
        ? 'Завтра'
        : new Intl.DateTimeFormat('ru-RU', {
            timeZone: timezone,
            weekday: 'short',
            day: 'numeric',
            month: 'short',
          }).format(new Date(start))
  const clock = new Intl.DateTimeFormat('ru-RU', {
    timeZone: timezone,
    hour: '2-digit',
    minute: '2-digit',
  })
  return `${day} · ${clock.format(new Date(start))}–${clock.format(new Date(end))}`
}
