import type { Chronotype, TaskType } from '@/shared/model/onboarding'
import { isTime, minutes } from './model'

export const CHRONOTYPES = [
  {
    value: 'lark',
    label: 'Жаворонок',
    description: 'Бодрее утром',
    peak: '08:00–11:00',
    workStart: '08:00',
    workEnd: '18:00',
    sleepTime: '23:00',
  },
  {
    value: 'dove',
    label: 'Голубь',
    description: 'Ровный дневной ритм',
    peak: '09:00–12:00',
    workStart: '09:00',
    workEnd: '19:00',
    sleepTime: '23:30',
  },
  {
    value: 'owl',
    label: 'Сова',
    description: 'Лучше после обеда и вечером',
    peak: '12:00–15:00',
    workStart: '12:00',
    workEnd: '22:00',
    sleepTime: '01:00',
  },
] as const

type DayWindow = {
  type: TaskType | 'rest'
  label: string
  start: number
  end: number
}

const WINDOWS: Record<Chronotype, DayWindow[]> = {
  lark: [
    { type: 'routine', label: 'Разгон: почта, планирование', start: 480, end: 600 },
    { type: 'intellectual', label: 'Интеллектуальное окно · пик 10–12', start: 600, end: 720 },
    { type: 'rest', label: 'Обед и отдых', start: 720, end: 780 },
    { type: 'intellectual', label: 'Вторая волна', start: 780, end: 870 },
    { type: 'physical', label: 'Физическое окно', start: 900, end: 960 },
    { type: 'routine', label: 'Рутина · эмоциональный спад', start: 960, end: 1080 },
  ],
  dove: [
    { type: 'routine', label: 'Разгон: почта, планирование', start: 540, end: 660 },
    { type: 'intellectual', label: 'Интеллектуальное окно · пик 11–13', start: 660, end: 780 },
    { type: 'rest', label: 'Обед и отдых', start: 780, end: 840 },
    { type: 'intellectual', label: 'Вторая волна', start: 840, end: 930 },
    { type: 'physical', label: 'Физическое окно', start: 960, end: 1020 },
    { type: 'routine', label: 'Рутина · эмоциональный спад', start: 1020, end: 1140 },
  ],
  owl: [
    { type: 'routine', label: 'Разгон: почта, планирование', start: 720, end: 840 },
    { type: 'intellectual', label: 'Интеллектуальное окно · пик 14–16', start: 840, end: 960 },
    { type: 'rest', label: 'Обед и отдых', start: 960, end: 1020 },
    { type: 'intellectual', label: 'Вторая волна', start: 1020, end: 1110 },
    { type: 'physical', label: 'Физическое окно', start: 1140, end: 1200 },
    { type: 'routine', label: 'Рутина · эмоциональный спад', start: 1200, end: 1320 },
  ],
}

export function chronotypePeak(chronotype: Chronotype): string {
  return CHRONOTYPES.find((item) => item.value === chronotype)!.peak
}

export function dayWindows(
  chronotype: Chronotype,
  workStart: string,
  workEnd: string,
): DayWindow[] {
  if (!isTime(workStart) || !isTime(workEnd)) return []
  const start = minutes(workStart)
  const end = minutes(workEnd)
  if (end <= start) return []
  const template = WINDOWS[chronotype]
  const windows = template
    .map((window) => ({
      ...window,
      start: Math.max(start, window.start),
      end: Math.min(end, window.end),
    }))
    .filter((window) => window.end > window.start)
  const firstStart = template[0].start
  const lastEnd = template[template.length - 1].end
  if (start < firstStart) {
    windows.unshift({
      type: 'routine',
      label: 'Спокойные дела и рутина',
      start,
      end: Math.min(end, firstStart),
    })
  }
  if (end > lastEnd) {
    windows.push({
      type: 'routine',
      label: 'Спокойные дела и рутина',
      start: Math.max(start, lastEnd),
      end,
    })
  }
  return windows
}

export function dayTicks(start: number, end: number): number[] {
  const ticks = [start]
  for (let tick = Math.floor(start / 60) * 60 + 60; tick < end; tick += 60) ticks.push(tick)
  ticks.push(end)
  return ticks
}
