import type { BiorhythmCycle } from '@/shared/model/biorhythm'
import type { SavedSchedule } from '@/shared/model/schedule'
import type { Task, TaskType } from '@/shared/model/task'
import { timelineClock } from './timelineModel'

export function daysSinceBirthLabel(birthDate: string, date: string) {
  const days = Math.round(
    (Date.parse(`${date}T00:00:00Z`) - Date.parse(`${birthDate}T00:00:00Z`)) / 86_400_000,
  )
  return `день ${new Intl.NumberFormat('ru-RU').format(days)}`
}

const CYCLE_TASK: Record<BiorhythmCycle, TaskType> = {
  physical: 'physical',
  emotional: 'creative',
  intellectual: 'intellectual',
}

export function cycleTaskHint(cycle: BiorhythmCycle, tasks: Task[], schedule: SavedSchedule) {
  const type = CYCLE_TASK[cycle]
  const matching = tasks.filter((task) => task.type === type && task.status !== 'skipped')
  if (!matching.length) return ''
  const descriptions = matching
    .map((task) => {
      const intervals = schedule.slots
        .filter((slot) => slot.kind === 'task' && slot.task_id === task.id)
        .sort((a, b) => Date.parse(a.start_at) - Date.parse(b.start_at))
      if (!intervals.length)
        return task.status !== 'done' ? `${task.title} — пока без времени в расписании.` : ''
      const times = intervals
        .map(
          (slot) =>
            `${timelineClock(Date.parse(slot.start_at), schedule.timezone)}–${timelineClock(Date.parse(slot.end_at), schedule.timezone)}`,
        )
        .join(', ')
      return `${task.title} — в ${intervals.length === 1 ? 'окне' : 'окнах'} ${times}.`
    })
    .filter(Boolean)
  return `${descriptions.slice(0, 3).join(' ')}${descriptions.length > 3 ? ' Остальные задачи — в плане дня.' : ''}`
}
