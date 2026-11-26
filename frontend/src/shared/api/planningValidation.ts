import { isCalendarDate } from '@/shared/lib/dateTime'
import { TASK_TYPES, type Task, type TaskList } from '@/shared/model/task'
import type { SavedSchedule, SchedulePlanningDetails } from '@/shared/model/schedule'

type RecordValue = Record<string, unknown>
const record = (value: unknown): value is RecordValue =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
const integer = (value: unknown, min = 0): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= min
const text = (value: unknown): value is string => typeof value === 'string'
const nullableText = (value: unknown) => value === null || text(value)
const strings = (value: unknown) => Array.isArray(value) && value.every(text)
const uuid = (value: unknown): value is string =>
  text(value) && /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(value)
const date = (value: unknown): value is string =>
  text(value) && value >= '0001-01-01' && isCalendarDate(value)
const timestamp = (value: unknown): value is string =>
  text(value) &&
  date(value.slice(0, 10)) &&
  /^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-]([01]\d|2[0-3]):[0-5]\d)$/.test(
    value,
  ) &&
  Number.isFinite(Date.parse(value))
const nullableTimestamp = (value: unknown) => value === null || timestamp(value)
const member = (value: unknown, values: readonly string[]) => text(value) && values.includes(value)

function invalid(): never {
  throw new Error('Сервер вернул некорректные данные задач или расписания. Повторите запрос.')
}

function task(value: unknown): value is Task {
  return (
    record(value) &&
    uuid(value.id) &&
    text(value.title) &&
    value.title.trim().length > 0 &&
    value.title.length <= 200 &&
    nullableText(value.description) &&
    member(value.type, Object.keys(TASK_TYPES)) &&
    member(value.priority, ['high', 'medium', 'low']) &&
    integer(value.duration_min, 5) &&
    value.duration_min <= 480 &&
    date(value.planned_date) &&
    nullableTimestamp(value.deadline) &&
    member(value.status, ['pending', 'scheduled', 'done', 'skipped']) &&
    nullableTimestamp(value.completed_at) &&
    integer(value.version, 1) &&
    timestamp(value.created_at) &&
    timestamp(value.updated_at) &&
    (value.preferred_start === null ||
      (text(value.preferred_start) &&
        /^([01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?$/.test(value.preferred_start))) &&
    typeof value.is_pinned === 'boolean' &&
    nullableTimestamp(value.pinned_start) &&
    typeof value.is_date_locked === 'boolean' &&
    nullableTimestamp(value.actual_start)
  )
}

export function readTask(value: unknown): Task {
  return task(value) ? value : invalid()
}

export function readTaskList(value: unknown): TaskList {
  if (
    !record(value) ||
    !Array.isArray(value.items) ||
    !value.items.every(task) ||
    !integer(value.total) ||
    !integer(value.limit, 1) ||
    value.limit > 100 ||
    !integer(value.offset) ||
    value.items.length > value.limit ||
    value.items.length > value.total
  )
    return invalid()
  return value as TaskList
}

function slot(value: unknown): boolean {
  return (
    record(value) &&
    uuid(value.id) &&
    member(value.kind, ['task', 'break', 'lunch', 'rest']) &&
    (value.kind === 'task' ? uuid(value.task_id) : value.task_id === null) &&
    timestamp(value.start_at) &&
    timestamp(value.end_at) &&
    Date.parse(value.end_at) > Date.parse(value.start_at) &&
    typeof value.is_pinned === 'boolean' &&
    strings(value.reason_codes) &&
    nullableText(value.explanation)
  )
}

export function readSavedSchedule(value: unknown): SavedSchedule {
  if (
    !record(value) ||
    !uuid(value.id) ||
    !date(value.planned_date) ||
    !text(value.timezone) ||
    !integer(value.version, 1) ||
    !text(value.algorithm_version) ||
    !value.algorithm_version.length ||
    !timestamp(value.generated_at) ||
    !Array.isArray(value.slots) ||
    !value.slots.every(slot) ||
    !Array.isArray(value.unscheduled) ||
    !value.unscheduled.every(
      (item) => record(item) && uuid(item.task_id) && strings(item.reason_codes),
    ) ||
    !record(value.metrics) ||
    ![
      'requested_min',
      'planned_min',
      'capacity_min',
      'high_intensity_min',
      'critical_level',
      'moved_min',
    ].every(
      (field) =>
        typeof value.metrics === 'object' &&
        value.metrics !== null &&
        integer((value.metrics as RecordValue)[field]),
    ) ||
    typeof value.metrics.load_factor !== 'number' ||
    !Number.isFinite(value.metrics.load_factor) ||
    !Array.isArray(value.warnings) ||
    !value.warnings.every(
      (item) =>
        record(item) &&
        text(item.code) &&
        text(item.message) &&
        member(item.level, ['info', 'warning', 'critical']) &&
        (item.task_id === null || uuid(item.task_id)) &&
        (item.target_date === null || date(item.target_date)),
    ) ||
    !Array.isArray(value.moves) ||
    !value.moves.every(
      (item) =>
        record(item) &&
        uuid(item.task_id) &&
        date(item.from_date) &&
        date(item.to_date) &&
        text(item.reason_code),
    )
  )
    return invalid()
  try {
    new Intl.DateTimeFormat('en', { timeZone: value.timezone })
  } catch {
    return invalid()
  }
  return value as SavedSchedule
}

export function readSchedulePlanningDetails(value: unknown): SchedulePlanningDetails {
  if (!record(value)) return invalid()
  const saved = readSavedSchedule(value.schedule)
  const reason = (value: unknown) => text(value) && /^[A-Z][A-Z0-9_]*$/.test(value)
  const reasons = (value: unknown) =>
    Array.isArray(value) && value.length > 0 && value.every(reason)
  const explained = (item: unknown): item is RecordValue =>
    record(item) && uuid(item.task_id) && text(item.explanation) && !!item.explanation.trim()
  if (
    !Array.isArray(value.recommendations) ||
    !value.recommendations.every(
      (item) =>
        explained(item) &&
        item.from_date === saved.planned_date &&
        date(item.to_date) &&
        item.to_date > saved.planned_date &&
        reason(item.reason_code),
    ) ||
    !Array.isArray(value.placement_explanations) ||
    !value.placement_explanations.every(
      (item) =>
        explained(item) &&
        item.planned_date === saved.planned_date &&
        timestamp(item.start_at) &&
        timestamp(item.end_at) &&
        (item.preservation === null ||
          member(item.preservation, ['pinned', 'done', 'started', 'past', 'system'])) &&
        reasons(item.reason_codes) &&
        saved.slots.some(
          (slot) =>
            slot.kind === 'task' &&
            slot.task_id === item.task_id &&
            Date.parse(slot.start_at) === Date.parse(item.start_at as string) &&
            Date.parse(slot.end_at) === Date.parse(item.end_at as string),
        ),
    ) ||
    !Array.isArray(value.unscheduled_explanations) ||
    !value.unscheduled_explanations.every(
      (item) =>
        explained(item) &&
        item.planned_date === saved.planned_date &&
        reasons(item.reason_codes) &&
        saved.unscheduled.some((task) => task.task_id === item.task_id),
    )
  )
    return invalid()
  const placed = saved.slots.filter((slot) => slot.kind === 'task')
  const referenced = new Set([
    ...placed.map((slot) => slot.task_id),
    ...saved.unscheduled.map((item) => item.task_id),
  ])
  const placements = new Set(
    value.placement_explanations.map((item) => `${item.task_id}:${Date.parse(item.start_at)}`),
  )
  if (
    placements.size !== placed.length ||
    placements.size !== value.placement_explanations.length ||
    new Set(value.unscheduled_explanations.map((item) => item.task_id)).size !==
      saved.unscheduled.length ||
    value.unscheduled_explanations.length !== saved.unscheduled.length ||
    new Set(value.recommendations.map((item) => item.task_id)).size !==
      value.recommendations.length ||
    value.recommendations.some((item) => !referenced.has(item.task_id))
  )
    return invalid()
  return value as SchedulePlanningDetails
}
