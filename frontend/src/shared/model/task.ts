/** Public task enums from the backend task schemas. */
export type TaskType = 'intellectual' | 'physical' | 'creative' | 'routine'

export const TASK_TYPES: Record<TaskType, string> = {
  intellectual: 'Интеллектуальная',
  physical: 'Физическая',
  creative: 'Творческая',
  routine: 'Рутина',
}

export type TaskPriority = 'high' | 'medium' | 'low'
export type TaskStatus = 'pending' | 'scheduled' | 'done' | 'skipped'

export type TaskFields = {
  title: string
  description: string | null
  type: TaskType
  priority: TaskPriority
  /** Required integer, 5–480 minutes. */
  duration_min: number
  /** Local calendar date YYYY-MM-DD in the profile timezone. */
  planned_date: string
  /** Local time HH:mm:ss; a preference, not a fixed appointment. */
  preferred_start: string | null
  /** Full timestamp with date, time and UTC offset; never a date-only value. */
  deadline: string | null
}

export type TaskPlacement =
  { is_pinned: false; pinned_start: null } | { is_pinned: true; pinned_start: string }

/** Form draft includes placement controls that the public write API does not support yet. */
export type TaskDraft = TaskFields & TaskPlacement

/** POST /tasks: placement, status and timestamps are read-only. */
export type TaskCreateRequest = Pick<
  TaskFields,
  'title' | 'type' | 'duration_min' | 'planned_date'
> &
  Partial<Pick<TaskFields, 'description' | 'priority' | 'deadline'>>

/** Omitted fields are unchanged; null clears a nullable field. */
export type TaskUpdateRequest = Partial<TaskCreateRequest> & { version: number }

/** Local preview callback; convert to TaskUpdateRequest before sending to the API. */
export type TaskDraftUpdate = Partial<TaskDraft> & { version: number }

export type TaskListQuery = {
  date?: string
  from?: string
  to?: string
  status?: TaskStatus
  type?: TaskType
  limit?: number
  offset?: number
}

export type TaskList = { items: Task[]; total: number; limit: number; offset: number }

export type Task = TaskFields & {
  is_pinned: boolean
  pinned_start: string | null
  id: string
  status: TaskStatus
  completed_at: string | null
  version: number
  created_at: string
  updated_at: string
}

/** UI values allow empty required controls until validation succeeds. */
export type TaskFormValues = {
  title: string
  description: string
  type: TaskType | ''
  durationMin: number | ''
  plannedDate: string
  /** datetime-local: YYYY-MM-DDTHH:mm in the profile timezone, without offset. */
  deadlineLocal: string
  priority: TaskPriority
  /** Local clock HH:mm, or an empty control. */
  preferredStart: string
  isPinned: boolean
  /** datetime-local in the profile timezone; required when isPinned is true. */
  pinnedStartLocal: string
}
