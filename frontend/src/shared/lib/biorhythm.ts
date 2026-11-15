import type { BiorhythmChartPoint, BiorhythmSeries } from '@/shared/model/biorhythm'

export function toBiorhythmChartPoints(series: BiorhythmSeries): BiorhythmChartPoint[] {
  return series.points.map((point) => ({
    timestamp: Date.parse(point.at),
    date: point.date,
    physical: point.cycles.physical.percent,
    emotional: point.cycles.emotional.percent,
    intellectual: point.cycles.intellectual.percent,
  }))
}
