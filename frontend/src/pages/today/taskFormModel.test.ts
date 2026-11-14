import { TASK_FORM_FIXTURES } from '@/shared/fixtures/planning'
import { emptyTaskForm, prepareTaskForm, type TaskFormContext } from './taskFormModel'

const context: TaskFormContext = {
  timezone: 'Asia/Yekaterinburg',
  workStart: '08:00',
  workEnd: '18:00',
  now: new Date('2026-11-11T04:42:00Z'),
}
const valid = () => structuredClone(TASK_FORM_FIXTURES.edit)

describe('task creation validation', () => {
  it('requires a name, type and explicit duration', () => {
    const result = prepareTaskForm(emptyTaskForm(context.timezone, context.now), context)
    expect(result.request).toBeNull()
    expect(result.errors).toHaveProperty('title')
    expect(result.errors).toHaveProperty('type')
    expect(result.errors).toHaveProperty('durationMin')
  })

  it.each([4, 481, 5.5, NaN])('rejects invalid duration %s', (durationMin) => {
    expect(prepareTaskForm({ ...valid(), durationMin }, context).errors.durationMin).toBeDefined()
  })

  it.each([5, 480])('accepts duration boundary %s', (durationMin) => {
    expect(prepareTaskForm({ ...valid(), durationMin }, context).request?.duration_min).toBe(
      durationMin,
    )
  })

  it.each(['2026-11-11T', 'T14:00', '2026-02-31T14:00', '2026-11-11T09:00'])(
    'rejects incomplete, invalid or past deadline %s',
    (deadlineLocal) => {
      expect(
        prepareTaskForm({ ...valid(), deadlineLocal }, context).errors.deadlineLocal,
      ).toBeDefined()
    },
  )

  it('normalizes the request and preserves the optional deadline', () => {
    const result = prepareTaskForm(
      {
        ...valid(),
        title: '  Подготовка  ',
        description: '  ',
        deadlineLocal: '',
        pinnedStartLocal: '2026-11-11T15:00',
      },
      context,
    )
    expect(result.errors).toEqual({})
    expect(result.request).toMatchObject({
      title: 'Подготовка',
      description: null,
      deadline: null,
      is_pinned: false,
      pinned_start: null,
    })
  })

  it('serializes the full deadline and pinned time in UTC', () => {
    const result = prepareTaskForm(
      {
        ...valid(),
        durationMin: 60,
        deadlineLocal: '2026-11-11T18:00',
        isPinned: true,
        pinnedStartLocal: '2026-11-11T15:00',
      },
      context,
    )
    expect(result.errors).toEqual({})
    expect(result.request).toMatchObject({
      deadline: '2026-11-11T13:00:00.000Z',
      is_pinned: true,
      pinned_start: '2026-11-11T10:00:00.000Z',
    })
  })

  it.each(['2026-11-11T', '2026-11-12T15:00', '2026-11-11T17:30'])(
    'rejects missing, wrong-day or overflowing pinned interval %s',
    (pinnedStartLocal) => {
      expect(
        prepareTaskForm(
          { ...valid(), durationMin: 90, isPinned: true, pinnedStartLocal, deadlineLocal: '' },
          context,
        ).errors.pinnedStartLocal,
      ).toBeDefined()
    },
  )

  it('checks the end of the pinned task against its deadline', () => {
    const result = prepareTaskForm(
      { ...valid(), isPinned: true, pinnedStartLocal: '2026-11-11T13:00' },
      context,
    )
    expect(result.errors.pinnedStartLocal).toContain('дедлайна')
  })

  it('rejects past days and preferred times outside the work window', () => {
    const result = prepareTaskForm(
      { ...valid(), plannedDate: '2026-11-10', preferredStart: '20:00' },
      context,
    )
    expect(result.errors.plannedDate).toBeDefined()
    expect(result.errors.preferredStart).toBeDefined()
  })

  it('uses the actual end of a task across a DST transition', () => {
    const result = prepareTaskForm(
      {
        ...valid(),
        plannedDate: '2027-03-28',
        durationMin: 120,
        deadlineLocal: '',
        isPinned: true,
        pinnedStartLocal: '2027-03-28T01:30',
      },
      { ...context, timezone: 'Europe/Berlin', workStart: '00:00', workEnd: '04:00' },
    )
    expect(result.errors.pinnedStartLocal).toBeDefined()
  })

  it('returns validation errors for invalid pinned durations without throwing', () => {
    const result = prepareTaskForm(
      { ...valid(), durationMin: Infinity, isPinned: true, pinnedStartLocal: '2026-11-11T15:00' },
      context,
    )
    expect(result.request).toBeNull()
    expect(result.errors.durationMin).toBeDefined()
  })
})
