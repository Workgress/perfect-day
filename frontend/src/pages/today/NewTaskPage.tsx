import { useState } from 'react'
import { useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import type { TaskCreateRequest } from '@/shared/model/task'
import { useSessionStore } from '@/stores/session'
import { TaskDialog } from './TaskDialog'
import { TaskForm } from './TaskForm'
import type { TaskFormOptions } from './taskFormSettings'

export function NewTaskPage() {
  const navigate = useNavigate()
  const timezone = useSessionStore((state) => state.timezone)
  const user = useSessionStore((state) => state.user)
  const generation = useSessionStore((state) => state.generation)
  const [preview, setPreview] = useState<{
    generation: number
    request: TaskCreateRequest
    options: TaskFormOptions
  } | null>(null)
  const close = () => navigate(paths.today)

  return (
    <TaskDialog
      title="Новая задача"
      description="Название, тип и длительность — обязательны."
      onClose={close}
    >
      <TaskForm
        key={generation}
        context={{
          timezone,
          workStart: user?.workStart ?? '08:00',
          workEnd: user?.workEnd ?? '18:00',
        }}
        onCancel={close}
        onSubmit={(request, options) => setPreview({ generation, request, options })}
        preview={preview?.generation === generation ? preview.request : null}
        previewOptions={preview?.generation === generation ? preview.options : null}
        onChange={() => setPreview(null)}
      />
    </TaskDialog>
  )
}
