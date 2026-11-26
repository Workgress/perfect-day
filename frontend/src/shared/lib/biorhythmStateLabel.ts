import { BIORHYTHM_PHASES, type BiorhythmReading } from '@/shared/model/biorhythm'

export function biorhythmStateLabel(reading: BiorhythmReading) {
  // The API's phase classifies the level; trend describes the curve's direction.
  if (reading.phase === 'peak' || reading.phase === 'minimum')
    return BIORHYTHM_PHASES[reading.phase]
  return reading.trend === 'up' ? 'Подъём' : 'Спад'
}
