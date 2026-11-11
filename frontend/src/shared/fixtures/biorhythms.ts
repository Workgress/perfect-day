import {
  BIORHYTHM_CYCLES,
  type BiorhythmCycle,
  type BiorhythmPhase,
  type BiorhythmPoint,
  type BiorhythmReading,
  type BiorhythmSeries,
} from '@/shared/model/biorhythm'
import { PLANNING_FIXTURE_CONTEXT } from './planning'

// Synthetic phases for layout, unrelated to any user's birth data.
const DEMO_OFFSETS: Record<BiorhythmCycle, number> = {
  physical: 6,
  emotional: 19,
  intellectual: 8,
}
const DAY_MS = 86_400_000
const REFERENCE_DAY = Date.parse('2026-11-11T00:00:00Z')

function reading(day: number, period: number): BiorhythmReading {
  const angle = (2 * Math.PI * day) / period
  const value = Math.round(Math.sin(angle) * 100)
  const phase: BiorhythmPhase =
    value >= 85 ? 'peak' : value <= -85 ? 'low' : Math.cos(angle) >= 0 ? 'rising' : 'falling'
  return { value, phase, day_in_cycle: (((day % period) + period) % period) + 1 }
}

function point(date: string): BiorhythmPoint {
  // UTC here is only for arithmetic on fixed fixture dates, not user time conversion.
  const offset = (Date.parse(`${date}T00:00:00Z`) - REFERENCE_DAY) / DAY_MS
  const cycles = Object.keys(BIORHYTHM_CYCLES) as BiorhythmCycle[]
  const criticalCycles = cycles.filter((cycle) => {
    const day = offset + DEMO_OFFSETS[cycle]
    const halfPeriod = BIORHYTHM_CYCLES[cycle].periodDays / 2
    return Math.floor((day - 0.5) / halfPeriod) !== Math.floor((day + 0.5) / halfPeriod)
  })
  return {
    date,
    at: new Date(`${date}T12:00:00+05:00`).toISOString(),
    cycles: {
      physical: reading(offset + DEMO_OFFSETS.physical, 23),
      emotional: reading(offset + DEMO_OFFSETS.emotional, 28),
      intellectual: reading(offset + DEMO_OFFSETS.intellectual, 33),
    },
    critical_cycles: criticalCycles,
    recommendation: criticalCycles.length
      ? 'Демонстрация: снизить нагрузку и оставить время на отдых.'
      : 'Демонстрация: выбрать подходящие задачи по фазам циклов.',
  }
}

function series(from: string, to: string): BiorhythmSeries {
  const points: BiorhythmPoint[] = []
  for (
    let instant = Date.parse(`${from}T00:00:00Z`);
    instant <= Date.parse(`${to}T00:00:00Z`);
    instant += DAY_MS
  ) {
    points.push(point(new Date(instant).toISOString().slice(0, 10)))
  }
  return {
    from,
    to,
    timezone: PLANNING_FIXTURE_CONTEXT.timezone,
    algorithm_version: 'demo-layout-v1',
    points,
  }
}

export const BIORHYTHM_FIXTURES = {
  week: series('2026-11-11', '2026-11-17'),
  month: series('2026-11-01', '2026-11-30'),
  threeMonths: series('2026-11-01', '2027-01-31'),
} satisfies Record<string, BiorhythmSeries>
