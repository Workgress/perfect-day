import { isCalendarDate } from '@/shared/lib/dateTime'
import { http } from './http'
import { readSavedSchedule } from './planningValidation'

export async function getSchedule(date: string, signal?: AbortSignal) {
  if (date < '0001-01-01' || !isCalendarDate(date)) throw new RangeError('Укажите дату YYYY-MM-DD.')
  const result = readSavedSchedule(
    await http<unknown>('/schedule', {
      query: { date },
      signal,
      cache: 'no-store',
    }),
  )
  if (result.planned_date !== date) throw new Error('Сервер вернул расписание на другую дату.')
  return result
}

export async function replanSchedule(date: string, version: number, signal?: AbortSignal) {
  if (date < '0001-01-01' || !isCalendarDate(date)) throw new RangeError('Укажите дату YYYY-MM-DD.')
  if (!Number.isSafeInteger(version) || version < 0)
    throw new RangeError('Не удалось определить версию расписания.')
  const result = await http<{ schedule: unknown }>('/schedule/replan', {
    method: 'POST',
    body: { planned_date: date, schedule_version: version, allow_date_change: false },
    signal,
  })
  const saved = readSavedSchedule(result?.schedule)
  if (saved.planned_date !== date || saved.version <= version)
    throw new Error('Сервер вернул другую дату или устаревшую версию расписания.')
  return saved
}
