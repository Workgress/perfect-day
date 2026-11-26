import { useIsMutating, useMutation, useMutationState, useQueryClient } from '@tanstack/react-query'
import { apiError, apiProblem } from '@/shared/api/errors'
import { scheduleKeys, taskKeys } from '@/shared/api/planningKeys'
import { getSchedule, replanSchedule } from '@/shared/api/schedule'
import { useSessionStore } from '@/stores/session'
import { taskSessionRequest } from './taskSessionRequest'
import { getDayTasks } from './useTodaySchedule'
import type { SavedSchedule } from '@/shared/model/schedule'

type ScheduleRevision = Pick<SavedSchedule, 'id' | 'version'>
type Command = {
  date: string
  generation: number
  version: number
  refreshOnly: boolean
  minimum?: ScheduleRevision
}
type ReplanResult = { blocked: boolean; message: string; minimum?: ScheduleRevision }

export function useReplanLock(generation: number) {
  const key = ['schedule-replan', generation]
  const pending = useIsMutating({ mutationKey: key }) > 0
  const history = useMutationState({
    filters: { mutationKey: key },
    select: (item) => (item.state.data as { blocked?: boolean } | undefined)?.blocked,
  })
  return pending || history.at(-1) === true
}

export function useScheduleReplan(date: string, generation: number, timezone: string) {
  const client = useQueryClient()
  const key = ['schedule-replan', generation]
  const pending = useIsMutating({ mutationKey: key }) > 0
  const taskPending = useIsMutating() > 0
  const history = useMutationState({
    filters: { mutationKey: key },
    select: (item) => ({
      command: item.state.variables as Command | undefined,
      status: item.state.status,
      result: item.state.data as ReplanResult | undefined,
    }),
  })
  const latest = history.filter((item) => item.command?.date === date).at(-1)
  const blocked = !!latest?.result?.blocked
  const current = () => useSessionStore.getState().generation === generation
  const refresh = async (command: Command, minimum = command.minimum) => {
    const [tasks, saved] = await taskSessionRequest(generation, (signal) =>
      Promise.all([
        getDayTasks(command.date, signal),
        getSchedule(command.date, signal).catch((error) => {
          if (apiProblem(error)?.code === 'SCHEDULE_NOT_FOUND') return null
          throw error
        }),
      ]),
    )
    if (saved && saved.timezone !== timezone)
      throw new Error('Часовой пояс расписания изменился. Обновите страницу.')
    if (minimum && (!saved || saved.id !== minimum.id || saved.version < minimum.version))
      throw new Error('Сервер вернул устаревшее расписание. Повторите загрузку.')
    if (!current()) throw new DOMException('Сессия изменилась', 'AbortError')
    await Promise.all([
      client.cancelQueries({ queryKey: taskKeys.all(generation) }),
      client.cancelQueries({ queryKey: scheduleKeys.all(generation) }),
    ])
    await Promise.all([
      client.invalidateQueries({ queryKey: taskKeys.all(generation), refetchType: 'none' }),
      client.invalidateQueries({ queryKey: scheduleKeys.all(generation), refetchType: 'none' }),
    ])
    if (!current()) throw new DOMException('Сессия изменилась', 'AbortError')
    client.setQueryData(taskKeys.day(generation, command.date), tasks)
    for (const task of tasks) client.setQueryData(taskKeys.detail(generation, task.id), task)
    if (saved) client.setQueryData(scheduleKeys.day(generation, command.date), saved)
    else client.removeQueries({ queryKey: scheduleKeys.day(generation, command.date), exact: true })
  }
  const mutation = useMutation({
    mutationKey: key,
    retry: false,
    mutationFn: async (command: Command): Promise<ReplanResult> => {
      if (command.refreshOnly) {
        try {
          await refresh(command)
          return { blocked: false, message: 'Данные обновлены. Проверьте план перед пересчётом.' }
        } catch (error) {
          return {
            blocked: true,
            message: `Не удалось обновить план. ${apiError(error)}`,
            minimum: command.minimum,
          }
        }
      }
      let saved: SavedSchedule | undefined
      let failure: unknown
      try {
        saved = await taskSessionRequest(generation, (signal) =>
          replanSchedule(command.date, command.version, signal),
        )
      } catch (error) {
        failure = error
      }
      if (!current()) throw new DOMException('Сессия изменилась', 'AbortError')
      try {
        await refresh(command, saved)
      } catch {
        return {
          blocked: true,
          minimum: saved ? { id: saved.id, version: saved.version } : undefined,
          message: saved
            ? 'План пересчитан, но не удалось загрузить результат. Обновите данные перед новым действием.'
            : 'Не удалось проверить результат пересчёта. Обновите данные перед новым действием.',
        }
      }
      if (saved) return { blocked: false, message: 'План и нагрузка обновлены.' }
      const conflict = ['SCHEDULE_VERSION_CONFLICT', 'TASK_VERSION_CONFLICT'].includes(
        apiProblem(failure)?.code ?? '',
      )
      return {
        blocked: false,
        message: conflict
          ? 'Расписание изменилось. Данные обновлены — проверьте план перед повторным пересчётом.'
          : `${apiError(failure)} Загружен актуальный план. Проверьте его перед повторным пересчётом.`,
      }
    },
  })
  return {
    pending,
    taskPending,
    blocked,
    message: latest?.status === 'success' ? latest.result?.message : undefined,
    execute: async (version: number, refreshOnly = false) => {
      if (client.isMutating() || (blocked && !refreshOnly)) return
      try {
        await mutation.mutateAsync({
          date,
          generation,
          version,
          refreshOnly,
          minimum: refreshOnly ? latest?.result?.minimum : undefined,
        })
      } catch {
        // Session changes abort the request and discard feedback for the previous account.
      }
    },
  }
}
