import {
  BIORHYTHM_CYCLES,
  type BiorhythmCycle,
  type BiorhythmCriticalInfo,
  type BiorhythmPhase,
  type BiorhythmPoint,
  type BiorhythmReading,
  type BiorhythmSeries,
  type BiorhythmSnapshot,
  type BiorhythmCriticalDays,
  type BiorhythmPeriod,
  type BiorhythmStep,
} from '@/shared/model/biorhythm'
import { PLANNING_FIXTURE_CONTEXT } from './planning'

const DEMO_OFFSETS: Record<BiorhythmCycle, number> = {
  physical: 6,
  emotional: 19,
  intellectual: 8,
}
const CYCLES = Object.keys(BIORHYTHM_CYCLES) as BiorhythmCycle[]
const CRITICAL_KINDS = ['none', 'single', 'double', 'triple'] as const
const DAY_MS = 86_400_000
const REFERENCE_NOON = Date.parse('2026-11-11T12:00:00+05:00')
const DEMO_CONTEXT = {
  timezone: PLANNING_FIXTURE_CONTEXT.timezone,
  algorithm_version: 'demo-layout-v2',
}

function demoReading(day: number, period: number): BiorhythmReading {
  const angle = (2 * Math.PI * day) / period
  const raw = Math.sin(angle)
  const value = Math.abs(raw) < 1e-12 ? 0 : raw
  const phase: BiorhythmPhase =
    value >= 0.5 ? 'peak' : value >= 0 ? 'rising' : value > -0.5 ? 'declining' : 'minimum'
  return {
    value,
    percent: Math.round(value * 1000) / 10 || 0,
    phase,
    trend: Math.cos(angle) >= 0 ? 'up' : 'down',
  }
}

function demoCritical(date: string): BiorhythmCriticalInfo {
  const offset = (Date.parse(`${date}T12:00:00+05:00`) - REFERENCE_NOON) / DAY_MS
  const crossings = CYCLES.flatMap((cycle) => {
    const halfPeriod = BIORHYTHM_CYCLES[cycle].periodDays / 2
    const index = Math.ceil((offset + DEMO_OFFSETS[cycle] - 0.5) / halfPeriod)
    const crossingDay = index * halfPeriod - DEMO_OFFSETS[cycle]
    return crossingDay < offset + 0.5
      ? [{ cycle, at: new Date(REFERENCE_NOON + crossingDay * DAY_MS).toISOString() }]
      : []
  }).sort(
    (a, b) =>
      Date.parse(a.at) - Date.parse(b.at) || CYCLES.indexOf(a.cycle) - CYCLES.indexOf(b.cycle),
  )
  const level = crossings.length as BiorhythmCriticalInfo['level']
  return { level, kind: CRITICAL_KINDS[level], crossings }
}

function demoPoint(date: string, hour = 12): BiorhythmPoint {
  const at = new Date(`${date}T${String(hour).padStart(2, '0')}:00:00+05:00`).toISOString()
  const offset = (Date.parse(at) - REFERENCE_NOON) / DAY_MS
  return {
    date,
    at,
    cycles: {
      physical: demoReading(offset + DEMO_OFFSETS.physical, 23),
      emotional: demoReading(offset + DEMO_OFFSETS.emotional, 28),
      intellectual: demoReading(offset + DEMO_OFFSETS.intellectual, 33),
    },
    critical: demoCritical(date),
  }
}

function demoSeries(
  start: string,
  end: string,
  step: BiorhythmStep = 'day',
  period: BiorhythmPeriod | null = null,
): BiorhythmSeries {
  const points: BiorhythmPoint[] = []
  for (
    let instant = Date.parse(`${start}T00:00:00Z`);
    instant <= Date.parse(`${end}T00:00:00Z`);
    instant += DAY_MS
  ) {
    const date = new Date(instant).toISOString().slice(0, 10)
    if (step === 'hour') for (let hour = 0; hour < 24; hour++) points.push(demoPoint(date, hour))
    else points.push(demoPoint(date))
  }
  return { ...DEMO_CONTEXT, start, end, step, period, points }
}

export const BIORHYTHM_FIXTURES = {
  day: demoSeries('2026-11-11', '2026-11-11', 'hour', 'day'),
  week: demoSeries('2026-11-11', '2026-11-17', 'day', 'week'),
  month: demoSeries('2026-11-11', '2026-12-10', 'day', 'month'),
  range: demoSeries('2026-11-01', '2027-01-01'),
} satisfies Record<string, BiorhythmSeries>

export const BIORHYTHM_SNAPSHOT_FIXTURE: BiorhythmSnapshot = {
  ...DEMO_CONTEXT,
  ...demoPoint(PLANNING_FIXTURE_CONTEXT.date),
}

export const BIORHYTHM_CRITICAL_DAYS_FIXTURE: BiorhythmCriticalDays = {
  ...DEMO_CONTEXT,
  start: BIORHYTHM_FIXTURES.week.start,
  end: BIORHYTHM_FIXTURES.week.end,
  days: BIORHYTHM_FIXTURES.week.points
    .filter((point) => point.critical.level > 0)
    .map((point) => ({ date: point.date, ...point.critical })),
}
