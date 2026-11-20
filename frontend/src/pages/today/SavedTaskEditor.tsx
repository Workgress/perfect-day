import { useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { apiError, apiProblem } from '@/shared/api/errors'
import { getTask, updateTask } from '@/shared/api/tasks'
import { taskUpdateRequest } from '@/shared/lib/taskRequests'
import type { Task, TaskDraft } from '@/shared/model/task'
import { Button } from '@/shared/ui/button/Button'
import { FormMessage } from '@/shared/ui/form-field/FormField'
import { TaskDialog } from './TaskDialog'
import { TaskForm } from './TaskForm'
import { taskToFormValues, type TaskFormContext } from './taskFormModel'
import { taskOptionsToSettings } from './taskFormSettings'
import { taskWriteFields } from './taskCreationErrors'
import { taskSessionRequest } from './taskSessionRequest'
import styles from './TaskForm.module.css'

export function SavedTaskEditor({
  task,
  context,
  generation,
  onClose,
  onSaved,
  onFresh,
}: {
  task: Task
  context: TaskFormContext
  generation: number
  onClose: () => void
  onSaved: (task: Task) => void
  onFresh: (task: Task) => void
}) {
  const [original, setOriginal] = useState(task)
  const [latest, setLatest] = useState<Task | null>(null)
  const [revision, setRevision] = useState(0)
  const [blocked, setBlocked] = useState(false)
  const [notice, setNotice] = useState('')
  const [checking, setChecking] = useState(false)
  const sending = useRef(false)
  const mutation = useMutation({
    retry: false,
    mutationFn: async (draft: TaskDraft) => {
      const body = taskUpdateRequest(draft, original)
      if (!body) return latest ?? original
      try {
        return await taskSessionRequest(generation, (signal) =>
          updateTask(
            original.id,
            {
              ...body,
              version: latest?.version ?? original.version,
            },
            signal,
          ),
        )
      } catch (error) {
        if (apiProblem(error)?.code === 'TASK_VERSION_CONFLICT') {
          setBlocked(true)
          setLatest(null)
          try {
            const fresh = await taskSessionRequest(generation, (signal) =>
              getTask(original.id, signal),
            )
            onFresh(fresh)
            setLatest(fresh)
            setBlocked(false)
            setNotice(
              `Задача изменилась. Актуальная версия: «${fresh.title}», ${fresh.planned_date}. Черновик сохранён. Повторное сохранение применит только изменённые вами поля.`,
            )
          } catch (readError) {
            setNotice(
              apiProblem(readError)?.code === 'TASK_NOT_FOUND'
                ? 'Задача удалена. Черновик сохранён в форме, сохранить его в эту задачу нельзя.'
                : 'Не удалось получить актуальную задачу. Черновик сохранён. Проверьте версию повторно.',
            )
          }
        }
        throw error
      }
    },
    onSuccess: onSaved,
    onSettled: () => {
      sending.current = false
    },
  })
  const close = () => {
    if (!sending.current) onClose()
  }
  const reload = async () => {
    if (sending.current) return
    sending.current = true
    setChecking(true)
    try {
      const fresh = await taskSessionRequest(generation, (signal) => getTask(original.id, signal))
      onFresh(fresh)
      setLatest(fresh)
      setBlocked(false)
      setNotice(
        `Актуальная задача: «${fresh.title}», ${fresh.planned_date}. Черновик сохранён; можно повторить сохранение или загрузить данные в форму.`,
      )
    } catch (error) {
      setNotice(apiError(error))
    } finally {
      sending.current = false
      setChecking(false)
    }
  }
  return (
    <TaskDialog
      title="Редактировать задачу"
      description="Измените нужные поля. Название, тип и длительность — обязательны."
      onClose={close}
      busy={mutation.isPending || checking}
    >
      <TaskForm
        key={revision}
        mode="edit"
        apiConnected
        context={{ ...context, originalTask: original }}
        initialValues={taskToFormValues(original, context.timezone)}
        initialSettings={taskOptionsToSettings(
          { recurrence: null, reminderMinutes: null },
          original.planned_date,
        )}
        onCancel={close}
        isSubmitting={mutation.isPending || checking}
        saveDisabled={blocked}
        submitLabel={latest ? 'Сохранить мои изменения' : undefined}
        submissionError={
          mutation.error && apiProblem(mutation.error)?.code !== 'TASK_VERSION_CONFLICT'
            ? apiError(mutation.error)
            : null
        }
        serverErrors={mutation.error ? taskWriteFields(mutation.error) : undefined}
        feedback={
          notice ? (
            <div className={styles.feedback}>
              <FormMessage tone="info">{notice}</FormMessage>
              {blocked ? (
                <Button variant="secondary" onClick={() => void reload()}>
                  Проверить версию повторно
                </Button>
              ) : null}
              {latest ? (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setOriginal(latest)
                    setLatest(null)
                    setNotice('')
                    setRevision((value) => value + 1)
                    mutation.reset()
                  }}
                >
                  Загрузить актуальную задачу и сбросить черновик
                </Button>
              ) : null}
            </div>
          ) : null
        }
        onChange={() => {
          if (!sending.current) mutation.reset()
        }}
        onSubmit={(draft) => {
          if (sending.current || blocked) return
          sending.current = true
          mutation.mutate(draft)
        }}
      />
    </TaskDialog>
  )
}
