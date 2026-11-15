export type BiorhythmCycle = 'physical' | 'emotional' | 'intellectual'
export type BiorhythmPhase = 'rising' | 'peak' | 'declining' | 'minimum'
export type BiorhythmTrend = 'up' | 'down'
export type BiorhythmStep = 'hour' | 'day'
export type BiorhythmPeriod = 'day' | 'week' | 'month'
export type BiorhythmCriticalKind = 'none' | 'single' | 'double' | 'triple'

export const MAX_BIORHYTHM_RANGE_DAYS = 62

export const BIORHYTHM_CYCLES: Record<BiorhythmCycle, { label: string; periodDays: number }> = {
  physical: { label: 'Физический', periodDays: 23 },
  emotional: { label: 'Эмоциональный', periodDays: 28 },
  intellectual: { label: 'Интеллектуальный', periodDays: 33 },
}

export const BIORHYTHM_PHASES: Record<BiorhythmPhase, string> = {
  rising: 'Подъём',
  peak: 'Пик',
  declining: 'Спад',
  minimum: 'Минимум',
}

export type BiorhythmReading = {
  value: number
  percent: number
  phase: BiorhythmPhase
  trend: BiorhythmTrend
}

export type BiorhythmCrossing = {
  cycle: BiorhythmCycle
  at: string
}

export type BiorhythmCriticalInfo = {
  level: 0 | 1 | 2 | 3
  kind: BiorhythmCriticalKind
  crossings: BiorhythmCrossing[]
}

export type BiorhythmPoint = {
  at: string
  date: string
  cycles: Record<BiorhythmCycle, BiorhythmReading>
  critical: BiorhythmCriticalInfo
}

export type BiorhythmRangeRequest = {
  from: string
  to: string
}

export type BiorhythmRequest = BiorhythmRangeRequest & { step?: BiorhythmStep }
export type BiorhythmSnapshotRequest = { at?: string }
export type BiorhythmForecastRequest = { period: BiorhythmPeriod }

export type BiorhythmContext = {
  timezone: string
  algorithm_version: string
}

export type BiorhythmSnapshot = BiorhythmContext & BiorhythmPoint

export type BiorhythmSeries = BiorhythmContext & {
  start: string
  end: string
  step: BiorhythmStep
  points: BiorhythmPoint[]
  period: BiorhythmPeriod | null
}

export type BiorhythmCriticalDay = BiorhythmCriticalInfo & { date: string }

export type BiorhythmCriticalDays = BiorhythmContext & {
  start: string
  end: string
  days: BiorhythmCriticalDay[]
}

export type BiorhythmChartPoint = {
  timestamp: number
  date: string
  physical: number
  emotional: number
  intellectual: number
}
