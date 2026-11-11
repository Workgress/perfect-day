/** Daily-series proposal. Personal calculations belong to the backend. */
export type BiorhythmCycle = 'physical' | 'emotional' | 'intellectual'
export type BiorhythmPhase = 'rising' | 'peak' | 'falling' | 'low'

export const BIORHYTHM_CYCLES: Record<BiorhythmCycle, { label: string; periodDays: number }> = {
  physical: { label: 'Физический', periodDays: 23 },
  emotional: { label: 'Эмоциональный', periodDays: 28 },
  intellectual: { label: 'Интеллектуальный', periodDays: 33 },
}

export const BIORHYTHM_PHASES: Record<BiorhythmPhase, string> = {
  rising: 'Подъём',
  peak: 'Пик',
  falling: 'Спад',
  low: 'Минимум',
}

export type BiorhythmReading = {
  /** Percentage from -100 to +100; no extra multiplication by 100 in the UI. */
  value: number
  phase: BiorhythmPhase
  day_in_cycle: number
}

export type BiorhythmPoint = {
  date: string
  /** Sample timestamp, proposed as local noon in the profile timezone. */
  at: string
  cycles: Record<BiorhythmCycle, BiorhythmReading>
  /** Cycles crossing zero during the whole local day, independent of the noon value. */
  critical_cycles: BiorhythmCycle[]
  recommendation: string | null
}

export type BiorhythmRequest = {
  /** Inclusive local dates YYYY-MM-DD, proposed maximum 93 days. */
  from: string
  to: string
}

export type BiorhythmSeries = BiorhythmRequest & {
  timezone: string
  algorithm_version: string
  points: BiorhythmPoint[]
}
