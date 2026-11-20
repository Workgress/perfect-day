import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { todayLoad } from './todayLoadModel'

const day = DAILY_SCHEDULE_FIXTURES.normal

describe('load within the profile work window', () => {
  it('does not count a task moved to another day even if an old slot still references it', () => {
    const task = { ...day.tasks[3], planned_date: '2026-11-12' }
    expect(
      todayLoad({
        ...day,
        tasks: [task],
        slots: day.slots.filter((slot) => slot.task_id === task.id),
      })?.planned,
    ).toBe(0)
  })
  it('counts lunch as routine and excludes rest outside working hours', () => {
    expect(todayLoad(day)).toEqual({
      types: { intellectual: 150, physical: 60, creative: 60, routine: 150, rest: 60 },
      planned: 480,
      capacity: 600,
      reserve: 120,
      percent: 80,
    })
  })

  it('clips intervals at both boundaries of the work window', () => {
    const load = todayLoad({ ...day, work_start: '11:45', work_end: '12:30' })!
    expect(load.types.routine).toBe(30)
    expect(load.types.rest).toBe(15)
    expect(load.planned).toBe(45)
    expect(load.capacity).toBe(45)
    expect(load.reserve).toBe(0)
  })

  it('uses elapsed work hours across a daylight-saving transition', () => {
    const load = todayLoad({
      ...day,
      date: '2026-10-25',
      timezone: 'Europe/Berlin',
      work_start: '00:00',
      work_end: '04:00',
      slots: [],
      tasks: [],
    })!
    expect(load.capacity).toBe(300)
    expect(load.planned).toBe(0)
    expect(load.reserve).toBe(300)
  })

  it('does not count a skipped task or invent an invalid work window', () => {
    const task = { ...day.tasks[2], status: 'skipped' as const }
    expect(
      todayLoad({
        ...day,
        tasks: [task],
        slots: day.slots.filter((slot) => slot.task_id === task.id),
      })?.planned,
    ).toBe(0)
    expect(todayLoad({ ...day, work_start: '18:00', work_end: '08:00' })).toBeNull()
  })
})
