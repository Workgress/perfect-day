import type { Chronotype } from '@/shared/model/onboarding'
import type { ScheduleSlot } from '@/shared/model/schedule'
import type { Task } from '@/shared/model/task'
import { formatPercent } from '@/pages/biorhythms/biorhythmChartModel'
import { timelineClock } from './timelineModel'

const CYCLE = {
  intellectual: { source: 'Интеллектуальный', name: 'интеллектуального' },
  physical: { source: 'Физический', name: 'физического' },
  creative: { source: 'Эмоциональный', name: 'эмоционального' },
}
const TASK_NAME = {
  intellectual: 'интеллектуальной',
  physical: 'физической',
  creative: 'творческой',
  routine: 'рутинной',
}

export function taskPlacementExplanation(
  task: Task,
  slot: ScheduleSlot,
  timezone: string,
  chronotype?: Chronotype | null,
) {
  const start = timelineClock(Date.parse(slot.start_at), timezone)
  const end = timelineClock(Date.parse(slot.end_at), timezone)
  const startHour = Number(start.slice(0, 2))
  const endHour = Number(end.slice(0, 2)) + Number(end.slice(3)) / 60
  const period =
    startHour >= 6 && endHour <= 12
      ? 'утреннее '
      : startHour >= 12 && endHour <= 18
        ? 'дневное '
        : startHour >= 18 && endHour >= startHour
          ? 'вечернее '
          : ''
  const person = chronotype ? { lark: 'жаворонка', owl: 'совы', dove: 'голубя' }[chronotype] : ''
  const window = `${period}окно${person ? ` ${person}` : ''} ${start}–${end}`
  // Saved planner-1.x plans expose the measured interval mean only in their explanation.
  // Unknown copy falls back to the actual interval; it never supplies a made-up percentage.
  const measurement = slot.explanation?.match(
    /(Интеллектуальный|Физический|Эмоциональный) биоритм: среднее за интервал ([+−-]?\d+(?:[.,]\d+)?)%/u,
  )
  const cycle = task.type === 'routine' ? null : CYCLE[task.type]
  const percent = measurement ? Number(measurement[2].replace('−', '-').replace(',', '.')) : NaN
  const measured =
    cycle &&
    measurement?.[1] === cycle.source &&
    Number.isFinite(percent) &&
    Math.abs(percent) <= 100
  const phase = percent >= 50 ? 'Пик' : percent >= 0 ? 'Подъём' : percent > -50 ? 'Спад' : 'Минимум'
  const opening = measured ? `${phase} ${cycle.name} цикла (${formatPercent(percent)})` : ''
  const placement = slot.is_pinned
    ? `${opening ? `${opening}. ` : ''}Время ${start}–${end} закреплено вами.`
    : opening
      ? `${opening} и ${window}.`
      : `Для ${TASK_NAME[task.type]} задачи выбрано ${window}.`
  const minutes = (Date.parse(slot.end_at) - Date.parse(slot.start_at)) / 60_000
  const plural = new Intl.PluralRules('ru-RU').select(minutes)
  const duration = `${minutes} ${plural === 'one' ? 'минута' : plural === 'few' ? 'минуты' : 'минут'}`
  const deadline = task.deadline ? Date.parse(task.deadline) : null
  const ending =
    deadline === null
      ? `Длительность задачи — ${duration}.`
      : Date.parse(slot.end_at) <= deadline
        ? `${duration} ${plural === 'one' ? 'помещается' : 'помещаются'} до дедлайна.`
        : `Окончание задачи позже дедлайна.`
  return `${placement} ${ending}`
}
