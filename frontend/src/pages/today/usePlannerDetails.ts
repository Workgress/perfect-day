import { useQuery } from '@tanstack/react-query'
import { scheduleKeys } from '@/shared/api/planningKeys'
import { getScheduleDetails } from '@/shared/api/schedule'
import { useSessionStore } from '@/stores/session'
import { taskSessionRequest } from './taskSessionRequest'

export function usePlannerDetails(
  source:
    { id: string; version: number; planned_date: string; timezone: string } | null | undefined,
) {
  const generation = useSessionStore((state) => state.generation)
  return useQuery({
    queryKey: scheduleKeys.details(generation, source?.planned_date ?? '', source?.version ?? 0),
    enabled: !!source,
    retry: false,
    queryFn: ({ signal }) =>
      taskSessionRequest(
        generation,
        async (requestSignal) => {
          const result = await getScheduleDetails(source!.planned_date, requestSignal)
          if (
            result.schedule.id !== source!.id ||
            result.schedule.version !== source!.version ||
            result.schedule.timezone !== source!.timezone
          )
            throw new Error(
              'План изменился. Обновите расписание, чтобы увидеть актуальные подсказки.',
            )
          return result
        },
        signal,
      ),
  })
}
