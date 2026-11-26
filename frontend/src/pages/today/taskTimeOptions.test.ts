import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { BIORHYTHM_FIXTURES } from '@/shared/fixtures/biorhythms'
import { savedFixture } from '@/test/planningDetails'
import { taskTimeOptions, nextTaskDays, taskTimeLabel } from './taskTimeOptions'

const fixture = DAILY_SCHEDULE_FIXTURES.normal
const base = {
  days: [{ date: fixture.date, schedule: null }],
  timezone: fixture.timezone,
  workStart: '08:00',
  workEnd: '18:00',
  duration: 60,
  type: 'creative' as const,
  now: new Date('2026-11-11T11:40:00+05:00'),
  deadline: '',
}

describe('free time suggestions', () => {
  it('excludes past starts and all occupied kinds, preserving touching boundaries', () => {
    const schedule = {
      ...savedFixture(fixture),
      slots: [
        {
          ...savedFixture(fixture).slots[0],
          kind: 'break' as const,
          task_id: null,
          start_at: '2026-11-11T12:00:00+05:00',
          end_at: '2026-11-11T17:00:00+05:00',
        },
      ],
    }
    const options = taskTimeOptions({ ...base, days: [{ date: fixture.date, schedule }] })
    expect(options).toHaveLength(1)
    expect(taskTimeLabel(options[0].start, options[0].end, base.timezone, base.now)).toBe(
      'Сегодня · 17:00–18:00',
    )
  })
  it('does not invent free days when no schedules were successfully read', () => {
    expect(taskTimeOptions({ ...base, days: [] })).toEqual([])
  })

  it('offers a gap starting immediately after a task outside the regular half-hour grid', () => {
    const schedule = {
      ...savedFixture(fixture),
      slots: [
        {
          ...savedFixture(fixture).slots[0],
          start_at: '2026-11-11T08:00:00+05:00',
          end_at: '2026-11-11T17:15:00+05:00',
        },
      ],
    }
    const options = taskTimeOptions({
      ...base,
      workEnd: '18:15',
      days: [{ date: fixture.date, schedule }],
    })
    expect(options).toHaveLength(1)
    expect(taskTimeLabel(options[0].start, options[0].end, base.timezone, base.now)).toBe(
      'Сегодня · 17:15–18:15',
    )
  })
  it('respects the deadline and full duration', () => {
    const options = taskTimeOptions({ ...base, deadline: '2026-11-11T13:00' })
    expect(options).toHaveLength(1)
    expect(Date.parse(options[0].end)).toBeLessThanOrEqual(Date.parse('2026-11-11T13:00:00+05:00'))
    expect(taskTimeOptions({ ...base, duration: 480 })).toEqual([])
    expect(taskTimeOptions({ ...base, duration: '' })).toEqual([])
  })
  it('offers different days and ranks creative tasks using emotional readings', () => {
    const rhythms = BIORHYTHM_FIXTURES.week
    const options = taskTimeOptions({
      ...base,
      days: nextTaskDays(fixture.date).map((date) => ({ date, schedule: null })),
      rhythms,
    })
    expect(options).toHaveLength(4)
    expect(new Set(options.map((item) => item.date)).size).toBe(4)
    expect(options.every((item) => item.explanation.includes('Эмоциональный цикл'))).toBe(true)
    expect(options[0].score).toBeGreaterThanOrEqual(options.at(-1)!.score)
  })
  it('ignores schedule and rhythm data from another timezone', () => {
    expect(
      taskTimeOptions({
        ...base,
        days: [{ date: fixture.date, schedule: { ...savedFixture(fixture), timezone: 'UTC' } }],
      }),
    ).toEqual([])
    const options = taskTimeOptions({
      ...base,
      rhythms: { ...BIORHYTHM_FIXTURES.week, timezone: 'UTC' },
    })
    expect(options.every((item) => item.explanation === 'Свободное окно в рабочем дне')).toBe(true)
  })
  it('handles calendar boundaries and timezone-local day labels', () => {
    expect(nextTaskDays('2026-12-31', 2)).toEqual(['2026-12-31', '2027-01-01'])
    expect(
      taskTimeLabel('2026-11-11T19:00:00Z', '2026-11-11T20:00:00Z', base.timezone, base.now),
    ).toBe('Завтра · 00:00–01:00')
  })
})
