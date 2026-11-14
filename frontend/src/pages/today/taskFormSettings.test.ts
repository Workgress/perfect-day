import { emptyTaskSettings, prepareTaskSettings } from './taskFormSettings'

describe('task repeat and reminder settings', () => {
  const day = '2026-11-15'

  it('uses the local calendar weekday for weekly repetition, including Sunday', () => {
    expect(
      prepareTaskSettings({ ...emptyTaskSettings(), repeat: 'weekly', reminder: '0' }, day).options,
    ).toEqual({
      recurrence: { frequency: 'weekly', interval: 1, weekdays: [7], until: null },
      reminderMinutes: 0,
    })
  })

  it.each([0, 53, 1.5, Infinity, ''])('rejects an invalid custom interval %s', (repeatInterval) => {
    const result = prepareTaskSettings(
      {
        ...emptyTaskSettings(),
        repeat: 'custom',
        repeatInterval: repeatInterval as number | '',
        repeatDays: [1],
      },
      day,
    )
    expect(result.errors.repeatInterval).toBeDefined()
    expect(result.options).toBeNull()
  })

  it('requires weekdays and a valid end date on or after the task day', () => {
    const result = prepareTaskSettings(
      { ...emptyTaskSettings(), repeat: 'custom', repeatUntil: '2026-11-14' },
      day,
    )
    expect(result.errors.repeatDays).toBeDefined()
    expect(result.errors.repeatUntil).toBeDefined()
    expect(result.options).toBeNull()
  })

  it('ignores retained custom settings when repetition is disabled', () => {
    expect(
      prepareTaskSettings(
        { ...emptyTaskSettings(), repeatInterval: '', repeatUntil: 'invalid', reminder: '' },
        day,
      ).options,
    ).toEqual({ recurrence: null, reminderMinutes: null })
  })

  it('normalizes custom weekdays and keeps the optional end date', () => {
    const result = prepareTaskSettings(
      {
        ...emptyTaskSettings(),
        repeat: 'custom',
        repeatInterval: 2,
        repeatDays: [5, 1, 5],
        repeatUntil: day,
      },
      day,
    )
    expect(result.options?.recurrence).toEqual({
      frequency: 'weekly',
      interval: 2,
      weekdays: [1, 5],
      until: day,
    })
  })
})
