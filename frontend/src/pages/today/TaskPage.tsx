import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate, useParams } from 'react-router'
import { editTaskPath, paths, taskPath } from '@/app/router/paths'
import { apiError, apiProblem } from '@/shared/api/errors'
import { scheduleKeys, taskKeys } from '@/shared/api/planningKeys'
import { getSchedule } from '@/shared/api/schedule'
import { deleteTask, getTask } from '@/shared/api/tasks'
import type { Task } from '@/shared/model/task'
import { Button } from '@/shared/ui/button/Button'
import { FormMessage } from '@/shared/ui/form-field/FormField'
import { useSessionStore } from '@/stores/session'
import { SavedTaskEditor } from './SavedTaskEditor'
import { TaskDetailsPanel } from './TaskDetailsPanel'
import { TaskDialog } from './TaskDialog'
import { TaskPlacementForm } from './TaskPlacementForm'
import { useTaskActions, type TaskAction } from './useTaskActions'
import { localDate } from '@/shared/lib/dateTime'
import { useCurrentTime } from '@/shared/lib/useCurrentTime'
import { taskSessionRequest } from './taskSessionRequest'
import styles from './TaskDetailsPanel.module.css'
import { usePlannerDetails } from './usePlannerDetails'
import { ActionConfirmation } from './ActionConfirmation'
import confirmationStyles from './ActionConfirmation.module.css'
import { taskTimeLabel } from './taskTimeOptions'
import { timelineDuration } from './timelineModel'

export function TaskPage() {
  return <TaskRoute editing={false} />
}
export function EditTaskPage() {
  return <TaskRoute editing />
}
function TaskRoute({ editing }: { editing: boolean }) {
  const generation = useSessionStore((state) => state.generation)
  const { taskId = '' } = useParams()
  return (
    <TaskContent
      key={`${generation}:${taskId}`}
      id={taskId}
      generation={generation}
      editing={editing}
    />
  )
}

function TaskContent({
  id,
  generation,
  editing,
}: {
  id: string
  generation: number
  editing: boolean
}) {
  const navigate = useNavigate()
  const location = useLocation()
  const client = useQueryClient()
  const timezone = useSessionStore((state) => state.timezone)
  const user = useSessionStore((state) => state.user)
  const sending = useRef(false)
  const mounted = useRef(false)
  const [notice, setNotice] = useState('')
  const [confirmation, setConfirmation] = useState<
    | { kind: 'delete'; version: number }
    | { kind: 'move'; version: number; scheduleVersion: number; date: string; start: string }
    | null
  >(null)
  const [placement, setPlacement] = useState<'pin' | 'move' | null>(
    location.state?.taskPlacement === 'move' ? 'move' : null,
  )
  const now = useCurrentTime()
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const current = () => useSessionStore.getState().generation === generation
  const query = useQuery({
    queryKey: taskKeys.detail(generation, id),
    queryFn: ({ signal }) =>
      taskSessionRequest(generation, (requestSignal) => getTask(id, requestSignal), signal),
    retry: false,
    refetchOnMount: 'always',
  })
  const task = query.data
  const schedule = useQuery({
    queryKey: scheduleKeys.day(generation, task?.planned_date ?? ''),
    queryFn: ({ signal }) =>
      taskSessionRequest(
        generation,
        (requestSignal) => getSchedule(task!.planned_date, requestSignal),
        signal,
      ),
    enabled: !!task && !editing,
    retry: false,
  })
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: taskKeys.lists(generation) })
    void client.invalidateQueries({ queryKey: scheduleKeys.all(generation) })
  }
  const source = schedule.isFetching
    ? undefined
    : apiProblem(schedule.error)?.code === 'SCHEDULE_NOT_FOUND'
      ? null
      : schedule.isError
        ? undefined
        : schedule.data
  const planner = usePlannerDetails(editing ? null : source)
  const actions = useTaskActions(task, source, timezone)
  const fresh = (value: Task) => {
    if (current()) client.setQueryData(taskKeys.detail(generation, id), value)
  }
  const mutation = useMutation({
    retry: false,
    mutationFn: async () => {
      if (!task) throw new Error('Задача не загружена')
      try {
        return await taskSessionRequest(generation, (signal) => {
          return deleteTask(id, task.version, signal)
        })
      } catch (error) {
        const code = apiProblem(error)?.code
        if (code === 'TASK_VERSION_CONFLICT') {
          const value = await taskSessionRequest(generation, (signal) => getTask(id, signal))
          fresh(value)
          if (current() && mounted.current) {
            setNotice('Задача изменилась. Данные обновлены — проверьте их и повторите действие.')
          }
        }
        throw error
      }
    },
    onSuccess: () => {
      if (!current()) return
      client.removeQueries({ queryKey: taskKeys.detail(generation, id), exact: true })
      invalidate()
      if (!mounted.current) return
      navigate(paths.today, {
        replace: true,
        state: { taskNotice: { generation, message: 'Задача удалена', detail: task?.title } },
      })
    },
    onError: (error) => {
      if (current() && mounted.current && apiProblem(error)?.code !== 'TASK_VERSION_CONFLICT')
        setNotice(apiError(error))
    },
    onSettled: () => {
      sending.current = false
    },
  })
  const close = () => {
    if (!sending.current && !actions.pending) navigate(paths.today, { replace: true })
  }
  if (
    !task ||
    !query.isFetchedAfterMount ||
    (query.isError && (editing || apiProblem(query.error)?.code === 'TASK_NOT_FOUND'))
  )
    return (
      <TaskDialog title="Задача" description="Данные задачи" onClose={close}>
        {query.isError ? (
          <>
            <FormMessage>
              {apiProblem(query.error)?.code === 'TASK_NOT_FOUND'
                ? 'Задача удалена или недоступна.'
                : apiError(query.error)}
            </FormMessage>
            <Button onClick={() => void query.refetch()}>Повторить загрузку</Button>
          </>
        ) : (
          <p role="status">Загружаем задачу…</p>
        )}
      </TaskDialog>
    )
  if (editing)
    return (
      <SavedTaskEditor
        task={task}
        generation={generation}
        context={{
          timezone,
          workStart: user?.workStart ?? '08:00',
          workEnd: user?.workEnd ?? '18:00',
        }}
        onClose={() => navigate(taskPath(id), { replace: true })}
        onFresh={fresh}
        onSaved={(value) => {
          if (!current()) return
          fresh(value)
          invalidate()
          if (mounted.current) navigate(taskPath(id), { replace: true })
        }}
      />
    )
  const remove = () => {
    if (sending.current || actions.pending || query.isError) return
    sending.current = true
    setNotice('')
    mutation.mutate()
  }
  const validSchedule = !schedule.isError && schedule.data?.timezone === timezone
  const busy = mutation.isPending || actions.pending
  const first = validSchedule
    ? schedule
        .data!.slots.filter((slot) => slot.kind === 'task' && slot.task_id === task.id)
        .sort((a, b) => Date.parse(a.start_at) - Date.parse(b.start_at))[0]
    : undefined
  const run = (action: TaskAction) => {
    setNotice('')
    if (sending.current || (query.isError && action.kind !== 'refresh'))
      return Promise.resolve(false)
    return actions.execute(action)
  }
  const pin = () => {
    if (task.is_pinned) void run({ kind: 'unpin' })
    else if (first) void run({ kind: 'pin', date: task.planned_date, start: first.start_at })
    else setPlacement('pin')
  }
  const placementLabel = (start: string) =>
    taskTimeLabel(
      start,
      new Date(Date.parse(start) + task.duration_min * 60_000).toISOString(),
      timezone,
      now,
    )
  return (
    <>
      <TaskDetailsPanel
        task={task}
        planning={planner.isSuccess && !planner.isFetching ? planner.data : undefined}
        explanationState={
          source && (planner.isPending || planner.isFetching) ? (
            <p>Загружаем подробные пояснения…</p>
          ) : source && planner.isError ? (
            <>
              <p>Подробные пояснения временно недоступны.</p>
              <Button
                size="s"
                variant="ghost"
                onClick={() => {
                  void planner.refetch()
                  void schedule.refetch()
                }}
              >
                Повторить загрузку пояснений
              </Button>
            </>
          ) : null
        }
        timezone={timezone}
        slots={validSchedule ? schedule.data!.slots.filter((slot) => slot.kind !== 'lunch') : []}
        placementMessage={
          schedule.isPending
            ? 'Загружаем расписание…'
            : !validSchedule
              ? 'Расписание недоступно. Размещение не подтверждено.'
              : undefined
        }
        busy={busy}
        actionsDisabled={actions.blocked || query.isError}
        onClose={close}
        onEdit={() => navigate(editTaskPath(id))}
        onMove={actions.placementReady ? () => setPlacement('move') : undefined}
        onPin={actions.placementReady ? pin : undefined}
        onStart={
          actions.placementReady && task.planned_date === localDate(now, timezone)
            ? () => void run({ kind: 'start' })
            : undefined
        }
        onComplete={() => void run({ kind: 'complete' })}
        onSkip={() => void run({ kind: 'skip' })}
        onReopen={() => void run({ kind: 'reopen' })}
        placementAction={
          placement ? (
            <TaskPlacementForm
              key={placement}
              date={task.planned_date}
              start={task.pinned_start ?? first?.start_at}
              timezone={timezone}
              busy={busy}
              disabled={actions.blocked || query.isError || !actions.placementReady}
              onCancel={() => setPlacement(null)}
              onSave={async (date, start) => {
                if (placement === 'move') {
                  setConfirmation({ kind: 'move', version: task.version, scheduleVersion: source?.version ?? 0, date, start })
                  return false
                }
                const saved = await run({ kind: placement, date, start })
                if (saved && current() && mounted.current) setPlacement(null)
                return saved
              }}
            />
          ) : null
        }
        recoveryAction={
          actions.blocked || query.isError || !actions.placementReady ? (
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => void run({ kind: 'refresh' })}
            >
              Обновить данные задачи
            </Button>
          ) : null
        }
        notice={
          confirmation
            ? null
            : busy
              ? 'Сохраняем…'
              : notice ||
                (query.isError
                  ? actions.blocked
                    ? actions.notice
                    : apiError(query.error)
                  : actions.notice || (mutation.error ? apiError(mutation.error) : null))
        }
        deleteAction={
          <div className={styles.deleteAction}>
            <Button
              variant="ghost"
              size="s"
              className={styles.deleteButton}
              disabled={busy || actions.blocked || query.isError}
              onClick={() => setConfirmation({ kind: 'delete', version: task.version })}
            >
              Удалить задачу
            </Button>
          </div>
        }
      />
      {confirmation ? (
        <ActionConfirmation
          title={confirmation.kind === 'delete' ? 'Удалить задачу?' : 'Перенести задачу'}
          busy={busy}
          onClose={() => setConfirmation(null)}
        >
          <p className={confirmation.kind === 'move' ? confirmationStyles.secondary : undefined}>
            {task.title}
            {confirmation.kind === 'move' ? ` · ${timelineDuration(task.duration_min)}` : ''}
          </p>
          <p className={confirmationStyles.secondary}>
            {first
              ? schedule.data!.slots.filter((slot) => slot.kind === 'task' && slot.task_id === task.id).map((slot) => taskTimeLabel(slot.start_at, slot.end_at, timezone, now)).join(', ')
              : `${task.planned_date.split('-').reverse().join('.')} · время не назначено`}
          </p>
          <p className={confirmationStyles.secondary}>
            {confirmation.kind === 'delete'
              ? 'Задача исчезнет из плана. Восстановление после удаления недоступно.'
              : `Новое время: ${placementLabel(confirmation.start)}`}
          </p>
          {confirmation.version !== task.version || (confirmation.kind === 'move' && source !== undefined && confirmation.scheduleVersion !== (source?.version ?? 0)) ? (
            <p role="alert">Задача или расписание изменились. Закройте окно и проверьте актуальные данные.</p>
          ) : null}
          {notice || actions.notice ? <p role="status">{notice || actions.notice}</p> : null}
          <div
            className={
              confirmation.kind === 'move' ? confirmationStyles.stack : confirmationStyles.actions
            }
          >
            {confirmation.kind === 'delete' ? (
              <Button
                variant="ghost"
                data-confirm-cancel
                disabled={busy}
                onClick={() => setConfirmation(null)}
              >
                Отмена
              </Button>
            ) : null}
            <Button
              className={confirmation.kind === 'delete' ? confirmationStyles.danger : undefined}
              disabled={
                busy || actions.blocked || query.isError || confirmation.version !== task.version ||
                (confirmation.kind === 'move' && (!actions.placementReady || confirmation.scheduleVersion !== (source?.version ?? 0)))
              }
              onClick={async () => {
                if (confirmation.kind === 'delete') {
                  remove()
                  return
                }
                const saved = await run({
                  kind: 'move',
                  date: confirmation.date,
                  start: confirmation.start,
                })
                if (saved && current() && mounted.current)
                  navigate(paths.today, {
                    replace: true,
                    state: {
                      taskNotice: {
                        generation,
                        message: 'Задача перенесена',
                        detail: placementLabel(confirmation.start),
                      },
                    },
                  })
              }}
            >
              {busy ? 'Сохраняем…' : confirmation.kind === 'delete' ? 'Удалить' : 'Перенести'}
            </Button>
            {confirmation.kind === 'move' ? (
              <Button
                variant="ghost"
                data-confirm-cancel
                disabled={busy}
                onClick={() => setConfirmation(null)}
              >
                Отмена
              </Button>
            ) : null}
          </div>
        </ActionConfirmation>
      ) : null}
    </>
  )
}
