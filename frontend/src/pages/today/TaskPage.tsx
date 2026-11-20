import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router'
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
import { taskSessionRequest } from './taskSessionRequest'
import styles from './TaskDetailsPanel.module.css'

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
  const client = useQueryClient()
  const timezone = useSessionStore((state) => state.timezone)
  const user = useSessionStore((state) => state.user)
  const sending = useRef(false)
  const mounted = useRef(false)
  const [notice, setNotice] = useState('')
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
        state: { taskNotice: { generation, message: 'Задача удалена' } },
      })
    },
    onSettled: () => {
      sending.current = false
    },
  })
  const close = () => {
    if (!sending.current) navigate(paths.today, { replace: true })
  }
  if (!task || !query.isFetchedAfterMount || query.isError)
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
    if (sending.current) return
    sending.current = true
    setNotice('')
    mutation.mutate()
  }
  const validSchedule = !schedule.isError && schedule.data?.timezone === timezone
  return (
    <TaskDetailsPanel
      exampleExplanation
      task={task}
      timezone={timezone}
      slots={validSchedule ? schedule.data!.slots : []}
      placementMessage={
        schedule.isPending
          ? 'Загружаем расписание…'
          : !validSchedule
            ? 'Расписание недоступно. Размещение не подтверждено.'
            : undefined
      }
      busy={mutation.isPending}
      onClose={close}
      onEdit={() => navigate(editTaskPath(id))}
      onMove={() => navigate(editTaskPath(id))}
      notice={
        mutation.isPending
          ? 'Сохраняем…'
          : notice || (mutation.error ? apiError(mutation.error) : null)
      }
      deleteAction={
        <div className={styles.deleteAction}>
          <Button
            variant="ghost"
            size="s"
            className={styles.deleteButton}
            disabled={mutation.isPending}
            onClick={remove}
          >
            Удалить задачу
          </Button>
        </div>
      }
    />
  )
}
