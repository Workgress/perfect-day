import { BIORHYTHM_FIXTURES } from '@/shared/fixtures/biorhythms'
import {
  PLOT,
  chartRange,
  curvePath,
  nearestPointIndex,
  pointX,
  pointY,
  shiftPeriod,
} from './biorhythmChartModel'

describe('biorhythm chart dates and geometry', () => {
  it('uses a Monday-based week across a year boundary', () => {
    expect(chartRange('2027-01-01', 'week')).toEqual({ start: '2026-12-28', end: '2027-01-03' })
  })
  it('supports leap months and three calendar months across a year boundary', () => {
    expect(chartRange('2028-02-17', 'month')).toEqual({ start: '2028-02-01', end: '2028-02-29' })
    expect(chartRange('2026-11-11', 'quarter')).toEqual({ start: '2026-11-01', end: '2027-01-31' })
    expect(shiftPeriod('2026-01-31', 'month', 1)).toBe('2026-02-28')
  })
  it('maps chart percentages to the full vertical scale', () => {
    expect(pointY(100)).toBe(PLOT.top)
    expect(pointY(0)).toBe((PLOT.top + PLOT.bottom) / 2)
    expect(pointY(-100)).toBe(PLOT.bottom)
  })
  it('finds the nearest timestamp and clamps pointer positions to the available points', () => {
    const points = BIORHYTHM_FIXTURES.week.points
    expect(nearestPointIndex(points, -100, 400)).toBe(0)
    expect(nearestPointIndex(points, 900, 400)).toBe(6)
    expect(nearestPointIndex(points, pointX(points[3].at, points, 400), 400)).toBe(3)
  })
  it('keeps distinct UTC positions for repeated local times on a DST transition', () => {
    const points = ['2026-10-25T00:00:00Z', '2026-10-25T01:00:00Z', '2026-10-25T02:00:00Z'].map(
      (at) => ({ ...BIORHYTHM_FIXTURES.week.points[0], at }),
    )
    expect(pointX(points[0].at, points, 400)).toBeLessThan(pointX(points[1].at, points, 400))
    expect(nearestPointIndex(points, pointX(points[1].at, points, 400), 400)).toBe(1)
  })
  it('handles empty and single-point curves without invalid coordinates', () => {
    expect(curvePath([])).toBe('')
    expect(curvePath([{ x: 100, y: 150 }])).toBe('M100,150')
    expect(
      pointX(BIORHYTHM_FIXTURES.week.points[0].at, [BIORHYTHM_FIXTURES.week.points[0]], 400),
    ).toBe(218)
  })
})
