import { useState } from 'react'
import type { Task, TaskCreateRequest, TaskUpdateRequest } from '@/shared/model/task'
import { TaskDialog } from './TaskDialog'
import { TaskForm } from './TaskForm'
import { taskToFormValues, type TaskFormContext } from './taskFormModel'
import { taskOptionsToSettings, type TaskFormOptions } from './taskFormSettings'

type EditTaskDialogProps = {
  task: Task
  context: TaskFormContext
  options?: TaskFormOptions
  onCancel: () => void
  onSubmit?: (request: TaskUpdateRequest, options: TaskFormOptions) => void
}

const EMPTY_OPTIONS: TaskFormOptions = { recurrence: null, reminderMinutes: null }

export function EditTaskDialog(props: EditTaskDialogProps) {
  return (
    <EditTaskContent
      key={`${props.task.id}:${props.task.version}:${props.context.timezone}`}
      {...props}
    />
  )
}

function EditTaskContent({
  task,
  context,
  options = EMPTY_OPTIONS,
  onCancel,
  onSubmit,
}: EditTaskDialogProps) {
  const [initialValues] = useState(() => taskToFormValues(task, context.timezone))
  const [initialSettings] = useState(() => taskOptionsToSettings(options, task.planned_date))
  const [preview, setPreview] = useState<{
    request: TaskCreateRequest
    options: TaskFormOptions
  } | null>(null)

  return (
    <TaskDialog
      title="Редактировать задачу"
      description="Измените нужные поля. Название, тип и длительность — обязательны."
      onClose={onCancel}
      returnFocusSelector="[data-task-edit-trigger]"
    >
      <TaskForm
        mode="edit"
        context={{ ...context, originalTask: task }}
        initialValues={initialValues}
        initialSettings={initialSettings}
        onCancel={onCancel}
        onSubmit={(request, nextOptions) => {
          const update = { ...request, version: task.version }
          setPreview({ request, options: nextOptions })
          onSubmit?.(update, nextOptions)
        }}
        preview={preview?.request}
        previewOptions={preview?.options}
        onChange={() => setPreview(null)}
      />
    </TaskDialog>
  )
}
