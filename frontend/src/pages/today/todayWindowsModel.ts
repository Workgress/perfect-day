import { dayWindows } from '@/pages/onboarding/chronotype'
import { resolveLocalDateTime } from '@/shared/lib/dateTime'
import type { Chronotype } from '@/shared/model/onboarding'
import type { DailySchedule } from '@/shared/model/schedule'

export function todayWindows(day: DailySchedule, chronotype?: Chronotype | null) {
  if (!chronotype) return []
  const instant = (minutes: number) => {
    const clock = `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
    return resolveLocalDateTime(`${day.date}T${clock}`, day.timezone)
  }
  return dayWindows(chronotype, day.work_start.slice(0, 5), day.work_end.slice(0, 5)).flatMap(
    (window) => {
      if (window.type === 'rest') return []
      const start = instant(window.start)
      const end = instant(window.end)
      return start.status === 'valid' && end.status === 'valid'
        ? [{ ...window, start: start.instant, end: end.instant }]
        : []
    },
  )
}

export type TodayWindow = ReturnType<typeof todayWindows>[number]
