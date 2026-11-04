import { EMPTY_ONBOARDING } from '@/shared/model/onboarding'
import { demoSlots, isTime, parseBirthDate, validateTasks } from './model'

describe('onboarding validation', () => {
  it.each([
    '31.04.2003',
    '29.02.2003',
    '00.01.2003',
    '20.13.2003',
    '20.09.1899',
    '01.01.2100',
    '2003-09-20',
    '',
  ])('rejects invalid birth date %s', (value) => {
    expect(parseBirthDate(value, new Date(2026, 10, 4))).toBeNull()
  })

  it('accepts a leap day and today but rejects tomorrow', () => {
    expect(parseBirthDate('29.02.2004')).toBe('2004-02-29')
    expect(parseBirthDate('04.11.2026', new Date(2026, 10, 4))).toBe('2026-11-04')
    expect(parseBirthDate('05.11.2026', new Date(2026, 10, 4))).toBeNull()
  })

  it('validates clock times without accepting overflow', () => {
    expect(isTime('00:00')).toBe(true)
    expect(isTime('23:59')).toBe(true)
    expect(isTime('24:00')).toBe(false)
    expect(isTime('12:60')).toBe(false)
  })

  const task = { id: 'one', title: 'Учёба', type: 'intellectual' as const, durationMin: 60 }

  it('requires tasks with names and valid durations', () => {
    expect(validateTasks(EMPTY_ONBOARDING)).toContain('хотя бы одну')
    expect(validateTasks({ ...EMPTY_ONBOARDING, tasks: [{ ...task, title: ' ' }] })).toContain(
      'название',
    )
    for (const durationMin of [0, 4, 481, 10.5, NaN]) {
      expect(validateTasks({ ...EMPTY_ONBOARDING, tasks: [{ ...task, durationMin }] })).toContain(
        'Длительность',
      )
    }
  })

  it('does not create an overflowing demo plan', () => {
    expect(validateTasks({ ...EMPTY_ONBOARDING, workEnd: '08:30', tasks: [task] })).toContain(
      'не помещаются',
    )
    expect(validateTasks({ ...EMPTY_ONBOARDING, workEnd: '08:00', tasks: [task] })).toContain(
      'начало и конец',
    )
  })

  it('places demo tasks consecutively inside the selected day', () => {
    const draft = {
      ...EMPTY_ONBOARDING,
      workStart: '09:30',
      tasks: [task, { ...task, id: 'two', durationMin: 90 }],
    }
    expect(validateTasks(draft)).toBeNull()
    expect(demoSlots(draft).map(({ start, end }) => [start, end])).toEqual([
      ['09:30', '10:30'],
      ['10:30', '12:00'],
    ])
  })
})
