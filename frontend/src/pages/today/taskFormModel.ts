import {
  isCalendarDate,
  localDate,
  localDateTime,
  resolveLocalDateTime,
} from '@/shared/lib/dateTime'
import { TASK_TYPES, type TaskCreateRequest, type TaskFormValues } from '@/shared/model/task'

export type TaskFormContext = {
  timezone: string
  workStart: string
  workEnd: string
  now?: Date
  originalTask?: TaskCreateRequest
}

export type TaskFormErrors = Partial<Record<keyof TaskFormValues, string>>

export const DURATION_PRESETS = [
  { value: 15, label: '15 мин' },
  { value: 30, label: '30 мин' },
  { value: 45, label: '45 мин' },
  { value: 60, label: '1 ч' },
  { value: 90, label: '1,5 ч' },
  { value: 120, label: '2 ч' },
]

export const TASK_TYPE_HINTS = {
  intellectual: 'Учёбу, анализ и сложные решения планируем на интеллектуальные окна.',
  creative: 'Творческие задачи и общение ставим на подъём эмоционального цикла.',
  physical: 'Для спорта и активных дел учитываем физический цикл.',
  routine: 'Рутинные дела оставляем на спокойные часы между пиками активности.',
}

export function emptyTaskForm(timezone: string, now = new Date()): TaskFormValues {
  return {
    title: '',
    description: '',
    type: '',
    durationMin: '',
    plannedDate: localDate(now, timezone),
    deadlineLocal: '',
    priority: 'medium',
    preferredStart: '',
    isPinned: false,
    pinnedStartLocal: '',
  }
}

export function taskToFormValues(task: TaskCreateRequest, timezone: string): TaskFormValues {
  return {
    title: task.title,
    description: task.description ?? '',
    type: task.type,
    durationMin: task.duration_min,
    plannedDate: task.planned_date,
    deadlineLocal: task.deadline ? localDateTime(new Date(task.deadline), timezone) : '',
    priority: task.priority,
    preferredStart: task.preferred_start?.slice(0, 5) ?? '',
    isPinned: task.is_pinned,
    pinnedStartLocal: task.pinned_start ? localDateTime(new Date(task.pinned_start), timezone) : '',
  }
}

function timeMinutes(value: string): number {
  return Number(value.slice(0, 2)) * 60 + Number(value.slice(3, 5))
}

export function prepareTaskForm(values: TaskFormValues, context: TaskFormContext) {
  const now = context.now ?? new Date()
  const errors: TaskFormErrors = {}
  const title = values.title.trim()
  const duration = values.durationMin
  const original = context.originalTask
  const unchangedPin = Boolean(
    original?.is_pinned &&
    values.isPinned &&
    values.plannedDate === original.planned_date &&
    duration === original.duration_min &&
    values.pinnedStartLocal === localDateTime(new Date(original.pinned_start), context.timezone),
  )
  if (!title || title.length > 200) errors.title = 'Введите название от 1 до 200 символов.'
  if (!Object.hasOwn(TASK_TYPES, values.type)) errors.type = 'Выберите тип задачи.'
  if (duration === '' || !Number.isInteger(duration) || duration < 5 || duration > 480)
    errors.durationMin = 'Укажите целую длительность от 5 до 480 минут.'
  if (!isCalendarDate(values.plannedDate)) errors.plannedDate = 'Укажите день задачи.'
  else if (
    values.plannedDate < localDate(now, context.timezone) &&
    values.plannedDate !== original?.planned_date
  )
    errors.plannedDate = 'Выберите сегодняшний или будущий день.'
  if (!['high', 'medium', 'low'].includes(values.priority)) errors.priority = 'Выберите приоритет.'

  const readDateTime = (field: 'deadlineLocal' | 'pinnedStartLocal') => {
    const previous = field === 'deadlineLocal' ? original?.deadline : original?.pinned_start
    if (
      previous &&
      values[field] === localDateTime(new Date(previous), context.timezone) &&
      (field === 'deadlineLocal' || unchangedPin)
    )
      return Date.parse(previous)
    const result = resolveLocalDateTime(values[field], context.timezone)
    if (result.status !== 'valid') {
      errors[field] =
        result.status === 'ambiguous'
          ? 'Это время повторяется при переводе часов. Выберите другое время.'
          : result.status === 'nonexistent'
            ? 'В этом часовом поясе такого времени нет из-за перевода часов.'
            : 'Укажите дату и время полностью.'
      return null
    }
    if (result.instant <= now.getTime()) errors[field] = 'Выберите время в будущем.'
    return result.instant
  }

  const deadline = values.deadlineLocal ? readDateTime('deadlineLocal') : null
  if (
    deadline !== null &&
    !errors.deadlineLocal &&
    values.deadlineLocal.slice(0, 10) < values.plannedDate
  )
    errors.deadlineLocal = 'Дедлайн не может быть раньше дня задачи.'

  if (values.preferredStart && values.preferredStart !== original?.preferred_start?.slice(0, 5)) {
    if (
      !/^([01]\d|2[0-3]):[0-5]\d$/.test(values.preferredStart) ||
      values.preferredStart < context.workStart ||
      values.preferredStart >= context.workEnd
    )
      errors.preferredStart = `Выберите время внутри рабочего дня: ${context.workStart}–${context.workEnd}.`
  }

  const pinned = values.isPinned ? readDateTime('pinnedStartLocal') : null
  if (pinned !== null && !errors.pinnedStartLocal && !errors.durationMin) {
    const startClock = values.pinnedStartLocal.slice(11)
    const endLocal = localDateTime(new Date(pinned + Number(duration) * 60_000), context.timezone)
    if (values.pinnedStartLocal.slice(0, 10) !== values.plannedDate)
      errors.pinnedStartLocal = 'Дата закрепления должна совпадать с днём задачи.'
    else if (
      !unchangedPin &&
      (startClock < context.workStart ||
        endLocal.slice(0, 10) !== values.plannedDate ||
        timeMinutes(endLocal.slice(11)) > timeMinutes(context.workEnd))
    )
      errors.pinnedStartLocal = `Задача должна помещаться в рабочий день: ${context.workStart}–${context.workEnd}.`
    else if (deadline !== null && pinned + Number(duration) * 60_000 > deadline)
      errors.pinnedStartLocal = 'Задача должна закончиться не позже дедлайна.'
  }

  let request: TaskCreateRequest | null = null
  if (Object.keys(errors).length === 0 && values.type !== '' && duration !== '') {
    request = {
      title,
      description: values.description.trim() || null,
      type: values.type,
      priority: values.priority,
      duration_min: duration,
      planned_date: values.plannedDate,
      preferred_start: values.preferredStart ? `${values.preferredStart}:00` : null,
      deadline: deadline === null ? null : new Date(deadline).toISOString(),
      ...(values.isPinned && pinned !== null
        ? { is_pinned: true, pinned_start: new Date(pinned).toISOString() }
        : { is_pinned: false, pinned_start: null }),
    }
  }
  return { errors, request }
}
