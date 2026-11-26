import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import type { DailySchedule } from '@/shared/model/schedule'
import { buildTimeline, timelineClock } from './timelineModel'

const now = new Date('2026-11-11T04:42:00Z')
const normal = DAILY_SCHEDULE_FIXTURES.normal

describe('daily timeline geometry', () => {
  it.each(['2026-11-10T22:34:00Z', '2026-11-11T18:34:00Z'])(
    'keeps the current-time line on today even outside the work window: %s',
    (at) => {
      const instant = new Date(at)
      const result = buildTimeline(DAILY_SCHEDULE_FIXTURES.empty, false, instant)
      expect(result.now?.label).toBe(timelineClock(instant.getTime(), normal.timezone))
      expect(result.start).toBeLessThanOrEqual(instant.getTime())
      expect(result.end).toBeGreaterThanOrEqual(instant.getTime())
    },
  )
  it('positions slots using their actual instants at 72 pixels per hour', () => {
    const result = buildTimeline(normal, true, now)
    const exam = result.rows.find((row) => row.task?.title === 'Подготовка к экзамену')!
    expect(exam.top).toBe(144)
    expect(exam.height).toBe(108)
    expect(result.now?.top).toBeCloseTo(122.4)
    expect(result.scheduledMinutes).toBe(360)
    for (let index = 1; index < result.rows.length; index++) {
      const previous = result.rows[index - 1]
      expect(previous.top + previous.height).toBeLessThanOrEqual(result.rows[index].top)
    }
  })

  it('collapses only the completed leading intervals and restores the full scale', () => {
    const collapsed = buildTimeline(normal, false, now)
    expect(collapsed.completed).toHaveLength(2)
    expect(timelineClock(collapsed.start, normal.timezone)).toBe('09:30')
    expect(collapsed.rows.some((row) => row.task?.status === 'done')).toBe(false)
    expect(buildTimeline(normal, true, now).rows).toHaveLength(normal.slots.length)
    expect(buildTimeline(normal, false, new Date('2026-11-11T02:00:00Z')).completed).toHaveLength(0)
  })

  it('keeps five-minute tasks proportional without enlarging or overlapping their intervals', () => {
    const day = structuredClone(normal)
    day.slots = [
      { ...day.slots[2], start_at: '2026-11-11T05:00:00Z', end_at: '2026-11-11T05:05:00Z' },
      { ...day.slots[5], start_at: '2026-11-11T05:05:00Z', end_at: '2026-11-11T05:20:00Z' },
    ]
    const result = buildTimeline(day, true, now)
    expect(result.rows[0].height).toBe(6)
    expect(result.rows[1].height).toBe(18)
    expect(result.rows[0].top + result.rows[0].height).toBe(result.rows[1].top)
  })

  it('shows only unoccupied gaps of at least an hour inside the work window', () => {
    const result = buildTimeline(normal, true, now)
    expect(
      result.gaps.map((gap) => [
        timelineClock(gap.start, normal.timezone),
        timelineClock(gap.end, normal.timezone),
      ]),
    ).toEqual([['17:00', '18:00']])
  })

  it('includes tasks outside the work window instead of cropping them away', () => {
    const day = structuredClone(normal)
    day.slots = [
      { ...day.slots[2], start_at: '2026-11-11T14:00:00Z', end_at: '2026-11-11T15:00:00Z' },
    ]
    const result = buildTimeline(day, true, now)
    expect(timelineClock(result.end, day.timezone)).toBe('20:00')
    expect(result.rows[0].top + result.rows[0].height).toBe(result.height)
  })

  it('keeps unplaced tasks off the scale and removes duplicate, completed and skipped backlog entries', () => {
    const day = structuredClone(DAILY_SCHEDULE_FIXTURES.overloaded)
    day.unscheduled_task_ids.push(day.unscheduled_task_ids[0], day.tasks[0].id, day.tasks[6].id)
    const result = buildTimeline(day, true, now)
    expect(result.unscheduled).toHaveLength(2)
    expect(result.rows).toHaveLength(normal.slots.length)
    expect(
      result.rows.every(
        (row) => !row.task || !result.unscheduled.some((task) => task?.id === row.task?.id),
      ),
    ).toBe(true)
  })

  it.each([
    ['2026-10-25', 432, true],
    ['2026-03-29', 288, false],
  ] as const)('uses elapsed time across a DST change on %s', (date, height, repeated) => {
    const day: DailySchedule = {
      ...DAILY_SCHEDULE_FIXTURES.empty,
      date,
      timezone: 'Europe/Berlin',
      work_start: '00:00:00',
      work_end: '04:00:00',
    }
    const result = buildTimeline(day, true, now)
    expect(result.height).toBe(height)
    expect(result.ticks.filter((tick) => tick.label === '02:00')).toHaveLength(repeated ? 2 : 0)
    if (repeated)
      expect(
        result.ticks.filter((tick) => tick.label === '02:00').map((tick) => tick.offset),
      ).toEqual(['GMT+2', 'GMT+1'])
  })

  it('does not show the current-time marker on another day', () => {
    expect(buildTimeline(normal, true, new Date('2026-11-12T04:42:00Z')).now).toBeNull()
  })

  it('rejects a missing task reference and a non-positive interval', () => {
    expect(() => buildTimeline({ ...normal, tasks: [] }, true, now)).toThrow(
      'некорректный интервал',
    )
    expect(() =>
      buildTimeline(
        { ...normal, slots: [{ ...normal.slots[0], end_at: normal.slots[0].start_at }] },
        true,
        now,
      ),
    ).toThrow('некорректный интервал')
  })
})
