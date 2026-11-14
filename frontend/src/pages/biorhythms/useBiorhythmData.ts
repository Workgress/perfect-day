import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getBiorhythmForecast, getBiorhythmSeries } from '@/shared/api/biorhythm'
import type { BiorhythmSeries } from '@/shared/model/biorhythm'
import { useSessionStore } from '@/stores/session'
import { addDays } from './biorhythmChartModel'

function localDate(timezone: string) {
  const parts = new Intl.DateTimeFormat('en', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  return ['year', 'month', 'day']
    .map((type) => parts.find((part) => part.type === type)!.value)
    .join('-')
}

export function useBiorhythmToday(timezone: string) {
  const [today, setToday] = useState(() => localDate(timezone))
  useEffect(() => {
    const update = () => setToday(localDate(timezone))
    const timer = window.setInterval(update, 30_000)
    window.addEventListener('focus', update)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', update)
    }
  }, [timezone])
  return today
}

export async function loadBiorhythmRange(start: string, end: string, signal?: AbortSignal) {
  const chunks: BiorhythmSeries[] = []
  for (let from = start; from <= end;) {
    const to = addDays(from, 61) < end ? addDays(from, 61) : end
    const chunk = await getBiorhythmSeries({ from, to, step: 'day' }, signal)
    if (
      chunks.length &&
      (chunk.timezone !== chunks[0].timezone ||
        chunk.algorithm_version !== chunks[0].algorithm_version)
    )
      throw new Error('Параметры расчёта изменились. Повторите запрос.')
    chunks.push(chunk)
    from = addDays(to, 1)
  }
  return {
    ...chunks[0],
    start,
    end,
    points: chunks.flatMap((chunk) => chunk.points),
  }
}

export function useBiorhythmData(start: string, end: string, today: string) {
  const generation = useSessionStore((state) => state.generation)
  const owner = useSessionStore((state) => state.ownerId)
  const timezone = useSessionStore((state) => state.timezone)
  const user = useSessionStore((state) => state.user)
  const status = useSessionStore((state) => state.status)
  return useQuery({
    queryKey: [
      'biorhythms',
      generation,
      owner,
      timezone,
      user?.birthDate,
      user?.birthTime,
      start,
      end,
      today,
    ],
    enabled: status === 'authenticated' && Boolean(user?.birthDate),
    queryFn: async ({ signal }) => {
      const [series, forecast] = await Promise.all([
        loadBiorhythmRange(start, end, signal),
        getBiorhythmForecast({ period: 'week' }, signal),
      ])
      if (series.timezone !== timezone || forecast.timezone !== timezone)
        throw new Error('Часовой пояс профиля изменился. Обновите страницу и повторите запрос.')
      if (series.algorithm_version !== forecast.algorithm_version)
        throw new Error('Параметры расчёта изменились. Повторите запрос.')
      if (forecast.start !== today)
        throw new Error(
          'Дата на устройстве отличается от даты сервера. Проверьте дату и повторите запрос.',
        )
      if (forecast.end !== addDays(today, 6))
        throw new Error('Сервер вернул неполный прогноз на неделю. Повторите запрос.')
      return { series, forecast }
    },
    retry: false,
    staleTime: 30_000,
    gcTime: 0,
  })
}
