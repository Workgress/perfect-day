import { isCalendarDate } from '@/shared/lib/dateTime'

export const REPEAT_OPTIONS = [
  { value: 'none', label: 'Не повторять' },
  { value: 'daily', label: 'Каждый день' },
  { value: 'weekly', label: 'Каждую неделю' },
  { value: 'custom', label: 'Свой график…' },
] as const

export const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

export const REMINDER_OPTIONS = [
  { value: '', label: 'Без напоминания' },
  { value: '0', label: 'В момент начала' },
  { value: '5', label: 'За 5 минут до начала' },
  { value: '10', label: 'За 10 минут до начала' },
  { value: '15', label: 'За 15 минут до начала' },
  { value: '30', label: 'За 30 минут до начала' },
  { value: '60', label: 'За час до начала' },
] as const

export type TaskFormSettings = {
  repeat: (typeof REPEAT_OPTIONS)[number]['value']
  repeatInterval: number | ''
  repeatDays: number[]
  repeatUntil: string
  reminder: string
}

export type TaskFormOptions = {
  recurrence: {
    frequency: 'daily' | 'weekly'
    interval: number
    weekdays: number[]
    until: string | null
  } | null
  reminderMinutes: number | null
}

export type TaskSettingsErrors = Partial<Record<keyof TaskFormSettings, string>>

export function emptyTaskSettings(): TaskFormSettings {
  return { repeat: 'none', repeatInterval: 1, repeatDays: [], repeatUntil: '', reminder: '5' }
}

export function prepareTaskSettings(values: TaskFormSettings, plannedDate: string) {
  const errors: TaskSettingsErrors = {}
  if (!REPEAT_OPTIONS.some((option) => option.value === values.repeat))
    errors.repeat = 'Выберите вариант повторения.'
  if (!REMINDER_OPTIONS.some((option) => option.value === values.reminder))
    errors.reminder = 'Выберите напоминание.'
  if (values.repeat === 'custom') {
    if (
      values.repeatInterval === '' ||
      !Number.isInteger(values.repeatInterval) ||
      values.repeatInterval < 1 ||
      values.repeatInterval > 52
    )
      errors.repeatInterval = 'Укажите интервал от 1 до 52 недель.'
    if (
      !values.repeatDays.length ||
      values.repeatDays.some((day) => !Number.isInteger(day) || day < 1 || day > 7)
    )
      errors.repeatDays = 'Выберите хотя бы один день недели.'
    if (
      values.repeatUntil &&
      (!isCalendarDate(values.repeatUntil) || values.repeatUntil < plannedDate)
    )
      errors.repeatUntil = 'Окончание повторов не может быть раньше дня задачи.'
  }
  let options: TaskFormOptions | null = null
  if (!Object.keys(errors).length) {
    const weekday = new Date(`${plannedDate}T00:00:00Z`).getUTCDay() || 7
    options = {
      recurrence:
        values.repeat === 'none'
          ? null
          : {
              frequency: values.repeat === 'daily' ? 'daily' : 'weekly',
              interval: values.repeat === 'custom' ? Number(values.repeatInterval) : 1,
              weekdays:
                values.repeat === 'daily'
                  ? []
                  : values.repeat === 'custom'
                    ? [...new Set(values.repeatDays)].sort((a, b) => a - b)
                    : [weekday],
              until: values.repeat === 'custom' ? values.repeatUntil || null : null,
            },
      reminderMinutes: values.reminder === '' ? null : Number(values.reminder),
    }
  }
  return { errors, options }
}
