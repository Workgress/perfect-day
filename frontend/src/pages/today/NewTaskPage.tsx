import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { paths, taskPath } from '@/app/router/paths'
import { createTask } from '@/shared/api/tasks'
import { scheduleKeys, taskKeys } from '@/shared/api/planningKeys'
import { taskCreateRequest } from '@/shared/lib/taskRequests'
import type { Task, TaskDraft } from '@/shared/model/task'
import { useSessionStore } from '@/stores/session'
import { TaskDialog } from './TaskDialog'
import { TaskForm } from './TaskForm'
import { taskCreationError } from './taskCreationErrors'
import { apiError } from '@/shared/api/errors'
import { FormMessage } from '@/shared/ui/form-field/FormField'
import { TaskPlacementForm } from './TaskPlacementForm'
import { taskSessionRequest } from './taskSessionRequest'
import { pinNewTask } from './pinNewTask'
import styles from './TaskForm.module.css'

type Command = { kind: 'create'; draft: TaskDraft } | { kind: 'pin'; date: string; start: string }

export function NewTaskPage() {
  const generation = useSessionStore((state) => state.generation)
  return <NewTaskContent key={generation} generation={generation} />
}

function NewTaskContent({ generation }: { generation: number }) {
  const navigate = useNavigate()
  const client = useQueryClient()
  const timezone = useSessionStore((state) => state.timezone)
  const user = useSessionStore((state) => state.user)
  const mounted = useRef(false)
  const sending = useRef(false)
  const createdTask = useRef<Task | null>(null)
  const requestedPin = useRef<{ date: string; start: string } | null>(null)
  const [recovery, setRecovery] = useState<{ task: Task; date: string; start: string } | null>(null)
  const current = () => useSessionStore.getState().generation === generation
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: taskKeys.all(generation) })
    void client.invalidateQueries({ queryKey: scheduleKeys.all(generation) })
  }
  const finish = (task: Task, requestedDate: string) => {
    if (current() && mounted.current)
      navigate(paths.today, {
        replace: true,
        state: { taskCreated: { task, generation, requestedDate } },
      })
  }
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const mutation = useMutation({
    mutationFn: (command: Command) =>
      taskSessionRequest(generation, async (signal) => {
        if (command.kind === 'create') {
          if (createdTask.current)
            throw new Error('Задача уже создана. Повторите только закрепление.')
          // Placement has its own API. CRUD must receive only the supported task fields.
          const task = await createTask(
            taskCreateRequest({
              ...command.draft,
              is_pinned: false,
              pinned_start: null,
            }),
            signal,
          )
          signal.throwIfAborted()
          if (!command.draft.is_pinned) return task
          createdTask.current = task
          requestedPin.current = {
            date: command.draft.planned_date,
            start: command.draft.pinned_start,
          }
        } else requestedPin.current = { date: command.date, start: command.start }
        if (!createdTask.current || !requestedPin.current)
          throw new Error('Не удалось определить созданную задачу.')
        return pinNewTask(
          createdTask.current.id,
          requestedPin.current.date,
          requestedPin.current.start,
          timezone,
          signal,
        )
      }),
    retry: false,
    onSuccess: (task, command) => {
      if (!current()) return
      client.setQueryData(taskKeys.detail(generation, task.id), task)
      invalidate()
      finish(task, command.kind === 'create' ? command.draft.planned_date : command.date)
    },
    onError: (error) => {
      if (!current()) return
      if (createdTask.current && requestedPin.current) {
        client.setQueryData(
          taskKeys.detail(generation, createdTask.current.id),
          createdTask.current,
        )
        invalidate()
        if (mounted.current) setRecovery({ task: createdTask.current, ...requestedPin.current })
        return
      }
      if (!taskCreationError(error).uncertain) return
      // A lost response can still mean a committed task. Refresh reads without replaying POST.
      void client.invalidateQueries({ queryKey: taskKeys.lists(generation) })
      void client.invalidateQueries({ queryKey: scheduleKeys.all(generation) })
    },
    onSettled: () => {
      sending.current = false
    },
  })
  const failure = useMemo(
    () => (mutation.error ? taskCreationError(mutation.error) : null),
    [mutation.error],
  )
  const close = () => {
    if (sending.current) return
    if (createdTask.current)
      navigate(paths.today, {
        replace: true,
        state: {
          taskNotice: {
            generation,
            message: `Задача «${createdTask.current.title}» создана. Проверьте её время в расписании.`,
          },
        },
      })
    else navigate(paths.today, { replace: true })
  }

  if (recovery)
    return (
      <TaskDialog
        title="Закрепление времени"
        description="Задача уже создана. Подтвердите время или выберите другое."
        onClose={close}
        busy={mutation.isPending}
        cancelLabel="К плану"
      >
        <div className={styles.form}>
          <div className={styles.body}>
            <div className={styles.fields}>
              <h3 className={styles.previewTitle}>{recovery.task.title}</h3>
              <FormMessage>
                Задача создана, но выбранное время пока не подтверждено.{' '}
                {mutation.error ? apiError(mutation.error) : ''} Повторное закрепление не создаст
                новую задачу.
              </FormMessage>
              <TaskPlacementForm
                date={recovery.date}
                start={recovery.start}
                timezone={timezone}
                busy={mutation.isPending}
                disabled={false}
                submitLabel="Закрепить время"
                cancelLabel="Открыть задачу"
                hint={`Часовой пояс: ${timezone}. Выбранное время будет закреплено.`}
                onCancel={() => navigate(taskPath(recovery.task.id), { replace: true })}
                onSave={async (date, start) => {
                  if (sending.current) return false
                  sending.current = true
                  try {
                    await mutation.mutateAsync({ kind: 'pin', date, start })
                    return true
                  } catch {
                    return false
                  }
                }}
              />
            </div>
          </div>
        </div>
      </TaskDialog>
    )

  return (
    <TaskDialog
      title="Новая задача"
      description="Название, тип и длительность — обязательны."
      onClose={close}
      busy={mutation.isPending}
    >
      <TaskForm
        apiConnected
        allowPinning
        context={{
          timezone,
          workStart: user?.workStart ?? '08:00',
          workEnd: user?.workEnd ?? '18:00',
        }}
        onCancel={close}
        isSubmitting={mutation.isPending}
        submissionError={failure?.message}
        serverErrors={failure?.fields}
        onSubmit={(draft) => {
          if (sending.current) return
          sending.current = true
          mutation.mutate({ kind: 'create', draft })
        }}
        onChange={() => {
          if (!sending.current) mutation.reset()
        }}
      />
    </TaskDialog>
  )
}
