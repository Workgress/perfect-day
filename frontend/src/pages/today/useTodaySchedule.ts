import { useQueries, useQuery } from '@tanstack/react-query'
import { apiProblem } from '@/shared/api/errors'
import { scheduleKeys, taskKeys } from '@/shared/api/planningKeys'
import { getSchedule } from '@/shared/api/schedule'
import { getTask, getTasks } from '@/shared/api/tasks'
import { dailySchedule } from '@/shared/lib/dailySchedule'
import type { DailySchedule } from '@/shared/model/schedule'
import type { Task } from '@/shared/model/task'
import { taskSessionRequest } from './taskSessionRequest'

// Read the whole day: the API returns at most 100 tasks per page.
export async function getDayTasks(date: string, signal: AbortSignal): Promise<Task[]> {
  const items: Task[] = []
  const ids = new Set<string>()
  let total: number | undefined
  do {
    const page = await getTasks({ date, limit: 100, offset: items.length }, signal)
    if (
      (total !== undefined && total !== page.total) ||
      page.offset !== items.length ||
      items.length + page.items.length > page.total ||
      (!page.items.length && items.length < page.total)
    )
      throw new Error('Список задач изменился во время загрузки. Обновите план дня.')
    total = page.total
    for (const task of page.items) {
      if (ids.has(task.id) || task.planned_date !== date)
        throw new Error('Список задач изменился во время загрузки. Обновите план дня.')
      ids.add(task.id)
      items.push(task)
    }
  } while (items.length < total)
  return items
}

export function useTodaySchedule(
  date: string,
  generation: number,
  work: {
    timezone: string
    work_start?: string
    work_end?: string
  },
  now: Date,
) {
  const tasks = useQuery({
    queryKey: taskKeys.day(generation, date),
    queryFn: ({ signal }) =>
      taskSessionRequest(generation, (requestSignal) => getDayTasks(date, requestSignal), signal),
    retry: false,
  })
  const schedule = useQuery({
    queryKey: scheduleKeys.day(generation, date),
    queryFn: ({ signal }) =>
      taskSessionRequest(generation, (requestSignal) => getSchedule(date, requestSignal), signal),
    retry: false,
  })
  const listed = new Set(tasks.data?.map((task) => task.id))
  const referenced = new Set([
    ...(schedule.data?.slots.flatMap((slot) => (slot.task_id ? [slot.task_id] : [])) ?? []),
    ...(schedule.data?.unscheduled.map((item) => item.task_id) ?? []),
  ])
  const missing =
    tasks.isSuccess && schedule.isSuccess && !tasks.isFetching && !schedule.isFetching
      ? [...referenced].filter((id) => !listed.has(id))
      : []
  const references = useQueries({
    queries: missing.map((id) => ({
      queryKey: taskKeys.detail(generation, id),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        taskSessionRequest(generation, (requestSignal) => getTask(id, requestSignal), signal),
      retry: false,
      staleTime: 0,
    })),
  })
  const absent = apiProblem(schedule.error)?.code === 'SCHEDULE_NOT_FOUND'
  const deleted = new Set(
    missing.filter((_, index) => apiProblem(references[index]?.error)?.code === 'TASK_NOT_FOUND'),
  )
  const stale = Boolean(
    schedule.data?.unscheduled.some((item) => deleted.has(item.task_id)) ||
    schedule.data?.slots.some(
      (slot) =>
        slot.task_id && deleted.has(slot.task_id) && Date.parse(slot.start_at) > now.getTime(),
    ),
  )
  const loading =
    tasks.isPending ||
    tasks.isFetching ||
    schedule.isPending ||
    schedule.isFetching ||
    references.some((query) => query.isPending || query.isFetching)
  let error: unknown =
    tasks.error ??
    (absent ? null : schedule.error) ??
    references.find((query) => query.isError && apiProblem(query.error)?.code !== 'TASK_NOT_FOUND')
      ?.error
  let day: DailySchedule | undefined
  if (!loading && !error && tasks.data && (schedule.data || (absent && !tasks.data.length))) {
    try {
      if (!work.work_start || !work.work_end)
        throw new Error('Не удалось получить рабочее время профиля. Обновите страницу.')
      if (schedule.data && schedule.data.timezone !== work.timezone)
        throw new Error('Рабочее время задано в другом часовом поясе, чем сохранённое расписание.')
      day = stale
        ? undefined
        : absent
          ? {
              date,
              timezone: work.timezone,
              work_start: work.work_start,
              work_end: work.work_end,
              schedule: null,
              tasks: [],
              slots: [],
              unscheduled_task_ids: [],
            }
          : dailySchedule(
              schedule.data!,
              [
                ...tasks.data,
                ...references.flatMap((query, index) =>
                  query.data && !deleted.has(missing[index]) ? [query.data] : [],
                ),
              ],
              { timezone: work.timezone, work_start: work.work_start, work_end: work.work_end },
              deleted,
            )
    } catch (cause) {
      error = cause
    }
  }
  return {
    version:
      !loading && !error && tasks.isSuccess && (schedule.isSuccess || absent)
        ? (schedule.data?.version ?? 0)
        : undefined,
    day,
    stale: !loading && !error && stale,
    metrics: stale ? undefined : schedule.data?.metrics,
    tasks: tasks.data ?? [],
    absent,
    loading,
    error,
    refresh: () =>
      Promise.allSettled([
        tasks.refetch(),
        schedule.refetch(),
        ...references.map((query) => query.refetch()),
      ]),
    warnings: absent || stale ? [] : (schedule.data?.warnings ?? []),
  }
}
