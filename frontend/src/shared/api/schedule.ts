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
