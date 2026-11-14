import { isCalendarDate } from '@/shared/lib/dateTime'
import {
  BIORHYTHM_CYCLES,
  BIORHYTHM_PHASES,
  MAX_BIORHYTHM_RANGE_DAYS,
  type BiorhythmCriticalDays,
  type BiorhythmPoint,
  type BiorhythmReading,
  type BiorhythmSeries,
  type BiorhythmSnapshot,
} from '@/shared/model/biorhythm'

const DAY_MS = 86_400_000
const CRITICAL_KINDS = ['none', 'single', 'double', 'triple']
const CYCLES = Object.keys(BIORHYTHM_CYCLES)

export function invalidBiorhythmResponse(): never {
  throw new Error('Сервер вернул некорректные данные биоритмов. Повторите запрос.')
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function finiteRange(value: unknown, min: number, max: number): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max
}

function calendarDate(value: unknown): value is string {
  return typeof value === 'string' && value >= '0001-01-01' && isCalendarDate(value)
}

export function isBiorhythmTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /^\d{4}-\d{2}-\d{2}[Tt ]([01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?:[Zz]|[+-]([01]\d|2[0-3]):[0-5]\d)$/.test(
      value,
    ) &&
    calendarDate(value.slice(0, 10)) &&
    Number.isFinite(Date.parse(value))
  )
}

function rangeDays(start: unknown, end: unknown): number | null {
  if (!calendarDate(start) || !calendarDate(end)) return null
  const days = (Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / DAY_MS + 1
  return days >= 1 && days <= MAX_BIORHYTHM_RANGE_DAYS ? days : null
}

export function validateBiorhythmRange(from: string, to: string) {
  if (rangeDays(from, to) === null)
    throw new RangeError('Укажите диапазон от 1 до 62 дней включительно в формате YYYY-MM-DD.')
}

function readContext(value: Record<string, unknown>) {
  if (
    typeof value.algorithm_version !== 'string' ||
    !value.algorithm_version.trim() ||
    typeof value.timezone !== 'string' ||
    !value.timezone.trim()
  )
    return invalidBiorhythmResponse()
  try {
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: value.timezone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    })
  } catch {
    return invalidBiorhythmResponse()
  }
}

function localDay(at: string, formatter: Intl.DateTimeFormat) {
  const parts = formatter.formatToParts(new Date(at))
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)!.value
  return `${part('year').padStart(4, '0')}-${part('month')}-${part('day')}`
}

function reading(value: unknown): value is BiorhythmReading {
  return (
    record(value) &&
    finiteRange(value.value, -1, 1) &&
    finiteRange(value.percent, -100, 100) &&
    typeof value.phase === 'string' &&
    Object.hasOwn(BIORHYTHM_PHASES, value.phase) &&
    (value.trend === 'up' || value.trend === 'down')
  )
}

function critical(value: unknown, date: string, formatter: Intl.DateTimeFormat): boolean {
  if (
    !record(value) ||
    !finiteRange(value.level, 0, 3) ||
    !Number.isInteger(value.level) ||
    value.kind !== CRITICAL_KINDS[value.level] ||
    !Array.isArray(value.crossings)
  )
    return false
  const cycles = new Set<string>()
  for (const crossing of value.crossings) {
    if (
      !record(crossing) ||
      typeof crossing.cycle !== 'string' ||
      !CYCLES.includes(crossing.cycle) ||
      cycles.has(crossing.cycle) ||
      !isBiorhythmTimestamp(crossing.at) ||
      localDay(crossing.at, formatter) !== date
    )
      return false
    cycles.add(crossing.cycle)
  }
  return cycles.size === value.level
}

function point(value: unknown, formatter: Intl.DateTimeFormat): value is BiorhythmPoint {
  return (
    record(value) &&
    calendarDate(value.date) &&
    isBiorhythmTimestamp(value.at) &&
    localDay(value.at, formatter) === value.date &&
    record(value.cycles) &&
    CYCLES.every((cycle) => reading((value.cycles as Record<string, unknown>)[cycle])) &&
    critical(value.critical, value.date, formatter)
  )
}

export function readBiorhythmSnapshot(value: unknown): BiorhythmSnapshot {
  if (!record(value)) return invalidBiorhythmResponse()
  const formatter = readContext(value)
  if (!point(value, formatter)) return invalidBiorhythmResponse()
  return value as BiorhythmSnapshot
}

export function readBiorhythmSeries(value: unknown): BiorhythmSeries {
  if (!record(value)) return invalidBiorhythmResponse()
  const formatter = readContext(value)
  const days = rangeDays(value.start, value.end)
  if (
    days === null ||
    (value.step !== 'day' && value.step !== 'hour') ||
    ![null, 'day', 'week', 'month'].includes(value.period as string | null) ||
    !Array.isArray(value.points)
  )
    return invalidBiorhythmResponse()
  const dates = new Set<string>()
  let previous = -Infinity
  for (const item of value.points) {
    if (
      !point(item, formatter) ||
      item.date < String(value.start) ||
      item.date > String(value.end) ||
      Date.parse(item.at) <= previous ||
      (value.step === 'day' && dates.has(item.date))
    )
      return invalidBiorhythmResponse()
    dates.add(item.date)
    previous = Date.parse(item.at)
  }
  if (dates.size !== days) return invalidBiorhythmResponse()
  return value as BiorhythmSeries
}

export function readBiorhythmCriticalDays(value: unknown): BiorhythmCriticalDays {
  if (!record(value)) return invalidBiorhythmResponse()
  const formatter = readContext(value)
  if (rangeDays(value.start, value.end) === null || !Array.isArray(value.days))
    return invalidBiorhythmResponse()
  let previous = ''
  for (const day of value.days) {
    if (
      !record(day) ||
      !calendarDate(day.date) ||
      day.date < String(value.start) ||
      day.date > String(value.end) ||
      day.date <= previous ||
      !critical(day, day.date, formatter) ||
      day.level === 0
    )
      return invalidBiorhythmResponse()
    previous = day.date
  }
  return value as BiorhythmCriticalDays
}
