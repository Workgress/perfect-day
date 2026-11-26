import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import type { SavedSchedule } from '@/shared/model/schedule'
import { dailySchedule } from './dailySchedule'

const day = DAILY_SCHEDULE_FIXTURES.normal
const saved: SavedSchedule = {
  id: day.schedule!.id,
  planned_date: day.date,
  timezone: day.timezone,
  version: 2,
  algorithm_version: 'planner-1.0.1',
  generated_at: '2026-11-11T02:00:00Z',
  slots: day.slots.map((slot) => ({ ...slot, reason_codes: ['ENERGY_RANKED'] })),
  unscheduled: [],
  warnings: [],
  moves: [],
  metrics: {
    requested_min: 30,
    planned_min: 30,
    capacity_min: 540,
    high_intensity_min: 0,
    critical_level: 0,
    load_factor: 1,
    moved_min: 0,
  },
}

describe('saved schedule to timeline data', () => {
  it('joins separate task responses and work clocks without losing slot timestamps or explanations', () => {
    const result = dailySchedule(saved, day.tasks, day)
    expect(result.date).toBe(saved.planned_date)
    expect(result.schedule).toEqual({ id: saved.id, version: 2 })
    expect(result.slots).toEqual(saved.slots.filter((slot) => slot.kind !== 'lunch'))
    expect(result.tasks).toEqual(day.tasks)
    expect(result.work_start).toBe(day.work_start)
  })

  it('requires every referenced task, including tasks outside the loaded list page', () => {
    expect(() => dailySchedule(saved, [], day)).toThrow('все задачи')
    expect(() =>
      dailySchedule(
        {
          ...saved,
          slots: [],
          unscheduled: [{ task_id: day.tasks[0].id, reason_codes: ['NO_CAPACITY'] }],
        },
        [],
        day,
      ),
    ).toThrow('все задачи')
  })

  it('keeps historical references even when their task date differs', () => {
    const moved = day.tasks.map((task) => ({ ...task, planned_date: '2026-11-12' }))
    const result = dailySchedule(saved, moved, day)
    expect(result.tasks.map((task) => task.id)).toContain(
      saved.slots.find((slot) => slot.task_id)?.task_id,
    )
  })

  it('does not combine saved timezone with clocks from a changed profile timezone', () => {
    expect(() => dailySchedule(saved, day.tasks, { ...day, timezone: 'UTC' })).toThrow(
      'другом часовом поясе',
    )
  })

  it('represents an empty saved day with system intervals, not a missing schedule', () => {
    const system = saved.slots.filter((slot) => slot.kind !== 'task')
    const result = dailySchedule({ ...saved, slots: system }, [], day)
    expect(result.tasks).toEqual([])
    expect(result.slots).toEqual(system.filter((slot) => slot.kind !== 'lunch'))
    expect(result.schedule).not.toBeNull()
  })
})
