import { useEffect, useMemo, useRef } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { createTask } from '@/shared/api/tasks'
import { scheduleKeys, taskKeys } from '@/shared/api/planningKeys'
import { taskCreateRequest } from '@/shared/lib/taskRequests'
import type { TaskDraft } from '@/shared/model/task'
import { useSessionStore } from '@/stores/session'
import { TaskDialog } from './TaskDialog'
import { TaskForm } from './TaskForm'
import { taskCreationError } from './taskCreationErrors'

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
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const mutation = useMutation({
    mutationFn: async (draft: TaskDraft) => {
      if (
        useSessionStore.getState().generation !== generation ||
        !useSessionStore.getState().accessToken
      )
        throw new DOMException('Сессия изменилась', 'AbortError')
      const controller = new AbortController()
      // Stop an authentication retry from sending the draft under a different account.
      const unsubscribe = useSessionStore.subscribe((state) => {
        if (state.generation !== generation) controller.abort()
      })
      try {
        return await createTask(taskCreateRequest(draft), controller.signal)
      } finally {
        unsubscribe()
      }
    },
    retry: false,
    onSuccess: (task, draft) => {
      if (useSessionStore.getState().generation !== generation) return
      client.setQueryData(taskKeys.detail(generation, task.id), task)
      void client.invalidateQueries({ queryKey: taskKeys.lists(generation) })
      // Creation can also move tasks and update future saved schedules.
      void client.invalidateQueries({ queryKey: scheduleKeys.all(generation) })
      if (mounted.current)
        navigate(paths.today, {
          replace: true,
          state: { taskCreated: { task, generation, requestedDate: draft.planned_date } },
        })
    },
    onError: (error) => {
      if (
        useSessionStore.getState().generation !== generation ||
        !taskCreationError(error).uncertain
      )
        return
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
    if (!sending.current) navigate(paths.today, { replace: true })
  }

  return (
    <TaskDialog
      title="Новая задача"
      description="Название, тип и длительность — обязательны."
      onClose={close}
      busy={mutation.isPending}
    >
      <TaskForm
        apiConnected
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
          mutation.mutate(draft)
        }}
        onChange={() => {
          if (!sending.current) mutation.reset()
        }}
      />
    </TaskDialog>
  )
}
