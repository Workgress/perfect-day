import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import type { SavedSchedule } from '@/shared/model/schedule'
import { cycleTaskHint, daysSinceBirthLabel } from './todayEnergyModel'

const fixture = DAILY_SCHEDULE_FIXTURES.normal
const schedule = { timezone: fixture.timezone, slots: fixture.slots } as SavedSchedule

describe('energy profile copy', () => {
  it('counts calendar days across leap years without a timezone shift', () => {
    expect(daysSinceBirthLabel('2024-02-28', '2024-03-01')).toBe('день 2')
    expect(daysSinceBirthLabel('2024-02-29', '2025-02-28')).toBe('день 365')
    expect(daysSinceBirthLabel('2024-03-01', '2024-03-02')).toBe('день 1')
  })

  it('uses actual task slots in the profile timezone for each cycle', () => {
    expect(cycleTaskHint('intellectual', fixture.tasks, schedule)).toBe(
      'Повторить конспект — в окне 08:30–09:30. Подготовка к экзамену — в окне 10:00–11:30.',
    )
    expect(cycleTaskHint('physical', fixture.tasks, schedule)).toBe(
      'Тренировка в зале — в окне 15:00–16:00.',
    )
    expect(cycleTaskHint('emotional', fixture.tasks, schedule)).toBe(
      `${fixture.tasks[3].title} — в окне 13:00–14:00.`,
    )
  })

  it('does not invent a window for unscheduled tasks or describe missing types', () => {
    const task = { ...fixture.tasks[2], status: 'pending' as const }
    expect(cycleTaskHint('physical', [task], schedule)).toBe('')
    expect(cycleTaskHint('intellectual', [task], { ...schedule, slots: [] })).toBe(
      'Подготовка к экзамену — пока без времени в расписании.',
    )
    expect(cycleTaskHint('intellectual', [{ ...task, status: 'skipped' }], schedule)).toBe('')
  })
})
