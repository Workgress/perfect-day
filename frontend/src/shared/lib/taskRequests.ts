import type { Task, TaskCreateRequest, TaskDraft, TaskUpdateRequest } from '@/shared/model/task'

const WRITABLE_FIELDS = [
  'title',
  'description',
  'type',
  'priority',
  'duration_min',
  'planned_date',
  'deadline',
] as const

export class UnsupportedTaskPlacementError extends Error {
  constructor() {
    super('Закрепление меняется в карточке задачи. Желаемое время пока недоступно.')
    this.name = 'UnsupportedTaskPlacementError'
  }
}

function sameInstant(left: string | null, right: string | null) {
  return (
    left === right || (left !== null && right !== null && Date.parse(left) === Date.parse(right))
  )
}

export function taskCreateRequest(draft: TaskDraft): TaskCreateRequest {
  if (draft.is_pinned || draft.pinned_start !== null || draft.preferred_start !== null)
    throw new UnsupportedTaskPlacementError()
  return Object.fromEntries(
    WRITABLE_FIELDS.map((field) => [field, draft[field]]),
  ) as TaskCreateRequest
}

/** Null means no writable changes. Keep the exact version of the task used to edit. */
export function taskUpdateRequest(draft: TaskDraft, original: Task): TaskUpdateRequest | null {
  if (
    draft.is_pinned !== original.is_pinned ||
    !sameInstant(draft.pinned_start, original.pinned_start) ||
    draft.preferred_start !== original.preferred_start
  )
    throw new UnsupportedTaskPlacementError()
  const changes = WRITABLE_FIELDS.filter((field) => {
    if (field === 'deadline' && draft.deadline && original.deadline)
      return Date.parse(draft.deadline) !== Date.parse(original.deadline)
    return draft[field] !== original[field]
  })
  return changes.length
    ? {
        ...Object.fromEntries(changes.map((field) => [field, draft[field]])),
        version: original.version,
      }
    : null
}
