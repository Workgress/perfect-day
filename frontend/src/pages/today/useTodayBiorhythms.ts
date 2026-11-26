import { useQuery } from '@tanstack/react-query'
import { getBiorhythmCriticalDays, getBiorhythmSeries } from '@/shared/api/biorhythm'
import { useSessionStore } from '@/stores/session'
import { addDays } from '@/pages/biorhythms/biorhythmChartModel'
import { taskSessionRequest } from './taskSessionRequest'

export function useTodayBiorhythms(date: string) {
  const generation = useSessionStore((state) => state.generation)
  const owner = useSessionStore((state) => state.ownerId)
  const timezone = useSessionStore((state) => state.timezone)
  const user = useSessionStore((state) => state.user)
  const status = useSessionStore((state) => state.status)
  const enabled = status === 'authenticated' && Boolean(user?.birthDate)
  return useQuery({
    queryKey: [
      'biorhythms',
      'today-profile',
      'v2',
      generation,
      owner,
      timezone,
      user?.birthDate,
      user?.birthTime,
      date,
    ],
    enabled,
    queryFn: ({ signal }) =>
      taskSessionRequest(
        generation,
        async (requestSignal) => {
          const [series, critical] = await Promise.all([
            getBiorhythmSeries(
              { from: addDays(date, -10), to: addDays(date, 10), step: 'day' },
              requestSignal,
            ),
            getBiorhythmCriticalDays({ from: date, to: addDays(date, 32) }, requestSignal),
          ])
          if (series.timezone !== timezone || critical.timezone !== timezone)
            throw new Error('Часовой пояс профиля изменился. Обновите страницу.')
          if (series.algorithm_version !== critical.algorithm_version)
            throw new Error('Параметры расчёта изменились. Повторите запрос.')
          return { series, critical }
        },
        signal,
      ),
    retry: false,
    staleTime: 60_000,
    gcTime: 0,
  })
}
