import { apiError, apiProblem } from '@/shared/api/errors'
import { HttpError } from '@/shared/api/http'
import type { TaskFormErrors } from './taskFormModel'
import { plannerMessage } from '@/shared/lib/plannerText'

const FIELDS = {
  title: 'title',
  description: 'description',
  type: 'type',
  priority: 'priority',
  duration_min: 'durationMin',
  planned_date: 'plannedDate',
  deadline: 'deadlineLocal',
} as const

export function taskWriteFields(error: unknown): TaskFormErrors {
  const fields: TaskFormErrors = {}
  const details = apiProblem(error)?.details.fields
  if (Array.isArray(details)) {
    for (const item of details) {
      if (!item || typeof item.field !== 'string' || typeof item.message !== 'string') continue
      const field = item.field.replace(/^body\./, '')
      if (Object.hasOwn(FIELDS, field))
        fields[FIELDS[field as keyof typeof FIELDS]] = plannerMessage(item.message)
    }
  }
  return fields
}

export function taskCreationError(error: unknown): { message: string; fields: TaskFormErrors } {
  const fields = taskWriteFields(error)
  const uncertain = !(error instanceof HttpError) || error.status >= 500
  return {
    fields,
    message: uncertain
      ? `${apiError(error)} Задача могла сохраниться. Проверьте список задач перед повторной отправкой.`
      : apiError(error),
  }
}
