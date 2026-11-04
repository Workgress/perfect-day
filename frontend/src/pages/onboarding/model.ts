import type { OnboardingDraft } from '@/shared/model/onboarding'

export function parseBirthDate(value: string, now = new Date()): string | null {
  const match = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(value.trim())
  if (!match) return null
  const [, day, month, year] = match
  const date = new Date(Number(year), Number(month) - 1, Number(day))
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  if (
    date.getFullYear() !== Number(year) ||
    date.getMonth() !== Number(month) - 1 ||
    date.getDate() !== Number(day) ||
    Number(year) < 1900 ||
    date > today
  )
    return null
  return `${year}-${month}-${day}`
}

export function isTime(value: string): boolean {
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(value)
}

export function minutes(value: string): number {
  const [hours, minute] = value.split(':').map(Number)
  return hours * 60 + minute
}

export function formatTime(value: number): string {
  return `${Math.floor(value / 60)
    .toString()
    .padStart(2, '0')}:${(value % 60).toString().padStart(2, '0')}`
}

export const TIME_OPTIONS = Array.from({ length: 48 }, (_, index) => formatTime(index * 30))

export function validateTasks({ tasks, workStart, workEnd }: OnboardingDraft): string | null {
  if (!tasks.length) return 'Добавьте хотя бы одну задачу.'
  if (tasks.some((task) => !task.title.trim() || task.title.trim().length > 200)) {
    return 'Укажите название каждой задачи: от 1 до 200 символов.'
  }
  if (
    tasks.some(
      (task) =>
        !Number.isInteger(task.durationMin) || task.durationMin < 5 || task.durationMin > 480,
    )
  ) {
    return 'Длительность каждой задачи — от 5 до 480 минут.'
  }
  if (!isTime(workStart) || !isTime(workEnd) || minutes(workEnd) <= minutes(workStart)) {
    return 'Проверьте начало и конец дня на предыдущем шаге.'
  }
  if (
    tasks.reduce((total, task) => total + task.durationMin, 0) >
    minutes(workEnd) - minutes(workStart)
  ) {
    return 'Задачи не помещаются в рабочий день. Сократите длительность или измените режим.'
  }
  return null
}

export function demoSlots({ tasks, workStart }: OnboardingDraft) {
  let cursor = minutes(workStart)
  return tasks.map((task) => {
    const start = cursor
    cursor += task.durationMin
    return { ...task, start: formatTime(start), end: formatTime(cursor) }
  })
}
