import type { BiorhythmPoint, BiorhythmSeries } from '@/shared/model/biorhythm'

export type ChartPeriod = 'week' | 'month' | 'quarter'
export type BiorhythmChartData = Pick<
  BiorhythmSeries,
  'start' | 'end' | 'timezone' | 'points' | 'step'
>
export const CYCLE_ORDER = ['physical', 'emotional', 'intellectual'] as const
export const PLOT = { left: 48, right: 12, top: 38, bottom: 258, height: 298 }
const DAY_MS = 86_400_000

function calendarInstant(date: string) {
  return Date.parse(`${date}T12:00:00Z`)
}

export function addDays(date: string, days: number) {
  return new Date(calendarInstant(date) + days * DAY_MS).toISOString().slice(0, 10)
}

export function shiftPeriod(date: string, period: ChartPeriod, direction: number) {
  if (period === 'week') return addDays(date, direction * 7)
  const value = new Date(calendarInstant(date))
  const day = value.getUTCDate()
  value.setUTCDate(1)
  value.setUTCMonth(value.getUTCMonth() + direction * (period === 'quarter' ? 3 : 1))
  const last = new Date(Date.UTC(value.getUTCFullYear(), value.getUTCMonth() + 1, 0)).getUTCDate()
  value.setUTCDate(Math.min(day, last))
  return value.toISOString().slice(0, 10)
}

export function chartRange(anchor: string, period: ChartPeriod) {
  if (period === 'week') {
    const weekday = new Date(calendarInstant(anchor)).getUTCDay() || 7
    const start = addDays(anchor, 1 - weekday)
    return { start, end: addDays(start, 6) }
  }
  const start = `${anchor.slice(0, 7)}-01`
  return { start, end: addDays(shiftPeriod(start, period, 1), -1) }
}

export function formatPercent(percent: number) {
  const value = new Intl.NumberFormat('ru-RU', {
    maximumFractionDigits: 1,
    signDisplay: 'exceptZero',
  }).format(percent)
  return `${value.replace('-', '−')} %`
}

export function formatDate(date: string, options: Intl.DateTimeFormatOptions) {
  return new Intl.DateTimeFormat('ru-RU', { ...options, timeZone: 'UTC' }).format(
    new Date(calendarInstant(date)),
  )
}

export function periodLabel(start: string, end: string, period: ChartPeriod) {
  if (period === 'month')
    return formatDate(start, { month: 'long', year: 'numeric' }).replace(' г.', '')
  if (period === 'week')
    return `${formatDate(start, { day: 'numeric', month: 'short' })} — ${formatDate(end, { day: 'numeric', month: 'short', year: 'numeric' })}`.replace(
      ' г.',
      '',
    )
  return `${formatDate(start, { month: 'short', year: 'numeric' })} — ${formatDate(end, { month: 'short', year: 'numeric' })}`.replaceAll(
    ' г.',
    '',
  )
}

export function pointX(at: string, points: BiorhythmPoint[], width: number) {
  if (points.length < 2) return (PLOT.left + width - PLOT.right) / 2
  const first = Date.parse(points[0].at)
  const last = Date.parse(points.at(-1)!.at)
  return PLOT.left + ((Date.parse(at) - first) / (last - first)) * (width - PLOT.left - PLOT.right)
}

export function pointY(percent: number) {
  return PLOT.top + ((100 - percent) / 200) * (PLOT.bottom - PLOT.top)
}

export function nearestPointIndex(points: BiorhythmPoint[], x: number, width: number) {
  if (points.length < 2) return 0
  const ratio = Math.max(0, Math.min(1, (x - PLOT.left) / (width - PLOT.left - PLOT.right)))
  const target =
    Date.parse(points[0].at) + ratio * (Date.parse(points.at(-1)!.at) - Date.parse(points[0].at))
  let nearest = 0
  for (let index = 1; index < points.length; index++)
    if (
      Math.abs(Date.parse(points[index].at) - target) <
      Math.abs(Date.parse(points[nearest].at) - target)
    )
      nearest = index
  return nearest
}

export function curvePath(points: { x: number; y: number }[]) {
  if (!points.length) return ''
  const slopes = points
    .slice(1)
    .map((point, index) => (point.y - points[index].y) / (point.x - points[index].x))
  const tangents = points.map((_, index) => {
    if (!index) return slopes[0] ?? 0
    if (index === points.length - 1) return slopes.at(-1) ?? 0
    const before = slopes[index - 1]
    const after = slopes[index]
    if (before * after <= 0) return 0
    const previousWidth = points[index].x - points[index - 1].x
    const nextWidth = points[index + 1].x - points[index].x
    const a = 2 * nextWidth + previousWidth
    const b = nextWidth + 2 * previousWidth
    return (a + b) / (a / before + b / after)
  })
  return points.reduce((path, point, index) => {
    if (!index) return `M${point.x},${point.y}`
    const previous = points[index - 1]
    const third = (point.x - previous.x) / 3
    return `${path} C${previous.x + third},${previous.y + tangents[index - 1] * third} ${point.x - third},${point.y - tangents[index] * third} ${point.x},${point.y}`
  }, '')
}
