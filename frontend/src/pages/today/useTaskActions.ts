import { useIsMutating, useMutation, useMutationState, useQueryClient } from '@tanstack/react-query'
import { apiError, apiProblem } from '@/shared/api/errors'
import { scheduleKeys, taskKeys } from '@/shared/api/planningKeys'
import { getSchedule } from '@/shared/api/schedule'
import {
  completeTask,
  getTask,
  moveTask,
  pinTask,
  reopenTask,
  skipTask,
  startTask,
  unpinTask,
} from '@/shared/api/tasks'
import type { Task } from '@/shared/model/task'
import { useSessionStore } from '@/stores/session'
import { taskSessionRequest } from './taskSessionRequest'

export type TaskAction =
  | { kind: 'complete' }
  | { kind: 'skip' }
  | { kind: 'reopen' }
  | { kind: 'start' }
  | { kind: 'unpin' }
  | { kind: 'refresh' }
  | { kind: 'pin' | 'move'; date: string; start: string }

export type ActionSchedule =
  { planned_date: string; timezone: string; version: number } | null | undefined
type Command = { task: Task; action: TaskAction; schedule: ActionSchedule }
type ActionResult = { notice: string }
const labels = {
  complete: 'Задача выполнена',
  skip: 'Задача пропущена',
  reopen: 'Задача возвращена в работу',
  start: 'Задача начата',
  pin: 'Время закреплено',
  unpin: 'Время откреплено',
  move: 'Задача перенесена, время закреплено',
  refresh: 'Данные обновлены. Проверьте план перед повторным действием.',
}

class ActionError extends Error {
  readonly needsRefresh: boolean
  constructor(message: string, needsRefresh: boolean) {
    super(message)
    this.needsRefresh = needsRefresh
  }
}

export function useTaskActions(task: Task | undefined, schedule: ActionSchedule, timezone: string) {
  const client = useQueryClient()
  const generation = useSessionStore((state) => state.generation)
  const key = ['task-actions', generation]
  const pending = useIsMutating({ mutationKey: key }) > 0
  // Keep feedback through the dashboard's loading/unmount cycle after invalidation.
  const history = useMutationState({
    filters: { mutationKey: key },
    select: (item) => ({
      command: item.state.variables as Command | undefined,
      status: item.state.status,
      error: item.state.error,
      result: item.state.data as ActionResult | undefined,
    }),
  })
  const latest = history.filter((item) => item.command?.task.id === task?.id).at(-1)
  const blocked =
    latest?.status === 'error' && latest.error instanceof ActionError && latest.error.needsRefresh
  const current = () => useSessionStore.getState().generation === generation
  const invalidate = async () => {
    if (!current()) return
    await Promise.all([
      client.invalidateQueries({ queryKey: taskKeys.all(generation) }),
      client.invalidateQueries({ queryKey: scheduleKeys.all(generation) }),
    ])
  }
  const readSchedule = async (date: string) => {
    try {
      const value = await taskSessionRequest(generation, (signal) => getSchedule(date, signal))
      if (value.timezone !== timezone)
        throw new Error('Часовой пояс расписания изменился. Обновите страницу.')
      return value
    } catch (error) {
      if (apiProblem(error)?.code === 'SCHEDULE_NOT_FOUND') return null
      throw error
    }
  }
  const refresh = async (id: string) => {
    const value = await taskSessionRequest(generation, (signal) => getTask(id, signal))
    const saved = await readSchedule(value.planned_date)
    if (!current()) return
    client.setQueryData(taskKeys.detail(generation, id), value)
    if (saved) client.setQueryData(scheduleKeys.day(generation, value.planned_date), saved)
    await invalidate()
  }
  const mutation = useMutation({
    mutationKey: key,
    retry: false,
    mutationFn: async ({
      task: selected,
      action,
      schedule: source,
    }: Command): Promise<ActionResult> => {
      if (action.kind === 'refresh') {
        try {
          await refresh(selected.id)
        } catch (error) {
          throw new ActionError(`Не удалось обновить данные. ${apiError(error)}`, true)
        }
        return { notice: labels.refresh }
      }
      await Promise.all([
        client.cancelQueries({ queryKey: taskKeys.all(generation) }),
        client.cancelQueries({ queryKey: scheduleKeys.all(generation) }),
      ])
      let written = false
      try {
        const value = await taskSessionRequest(generation, async (signal) => {
          if (action.kind === 'complete') return completeTask(selected.id, selected.version, signal)
          if (action.kind === 'skip') return skipTask(selected.id, selected.version, signal)
          if (action.kind === 'reopen') return reopenTask(selected.id, selected.version, signal)
          if (
            source === undefined ||
            (source &&
              (source.planned_date !== selected.planned_date || source.timezone !== timezone))
          )
            throw new Error('Сначала загрузите актуальное расписание задачи.')
          const versions: Record<string, number> = { [selected.planned_date]: source?.version ?? 0 }
          if (action.kind === 'unpin')
            return unpinTask(selected.id, selected.version, versions[selected.planned_date], signal)
          if (action.kind === 'start')
            return startTask(
              selected.id,
              { version: selected.version, schedule_versions: versions },
              signal,
            )
          if (action.date !== selected.planned_date) {
            const target = await readSchedule(action.date)
            versions[action.date] = target?.version ?? 0
          }
          const body = {
            planned_date: action.date,
            start_at: action.start,
            version: selected.version,
            schedule_versions: versions,
          }
          return action.kind === 'pin'
            ? pinTask(selected.id, body, signal)
            : moveTask(selected.id, body, signal)
        })
        written = true
        if (!current()) throw new DOMException('Сессия изменилась', 'AbortError')
        client.setQueryData(taskKeys.detail(generation, selected.id), value)
        await invalidate()
        return { notice: labels[action.kind] }
      } catch (error) {
        if (!current()) throw error
        if (written)
          return { notice: `${labels[action.kind]}. Обновите план, чтобы проверить расписание.` }
        let refreshed = false
        try {
          await refresh(selected.id)
          refreshed = true
        } catch {
          await invalidate()
        }
        const conflict = ['TASK_VERSION_CONFLICT', 'SCHEDULE_VERSION_CONFLICT'].includes(
          apiProblem(error)?.code ?? '',
        )
        const message = conflict ? 'Задача или расписание изменились.' : apiError(error)
        throw new ActionError(
          `${message} ${refreshed ? 'Данные обновлены — проверьте их перед повторным действием.' : 'Не удалось проверить результат. Обновите данные перед повторным действием.'}`,
          !refreshed,
        )
      }
    },
  })
  return {
    pending,
    blocked,
    placementReady:
      schedule !== undefined &&
      (!schedule ||
        (schedule.planned_date === task?.planned_date && schedule.timezone === timezone)),
    notice:
      latest?.status === 'error'
        ? apiError(latest.error)
        : latest?.status === 'success'
          ? latest.result?.notice
          : null,
    execute: async (action: TaskAction) => {
      if (
        !task ||
        client.isMutating({ mutationKey: key }) ||
        (blocked && action.kind !== 'refresh')
      )
        return false
      try {
        await mutation.mutateAsync({ task, action, schedule })
        return true
      } catch {
        return false
      }
    },
  }
}
