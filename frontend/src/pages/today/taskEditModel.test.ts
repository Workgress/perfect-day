import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { prepareTaskForm, taskToFormValues } from './taskFormModel'
import {
  prepareTaskSettings,
  taskOptionsToSettings,
  type TaskFormOptions,
} from './taskFormSettings'

const originalTask = DAILY_SCHEDULE_FIXTURES.normal.tasks[4]
const context = {
  timezone: 'Asia/Yekaterinburg',
  workStart: '08:00',
  workEnd: '18:00',
  now: new Date('2026-11-14T12:00:00Z'),
  originalTask,
}

describe('task editing validation', () => {
  it('allows changing a title without rescheduling an unchanged past pinned task', () => {
    const values = taskToFormValues(originalTask, context.timezone)
    expect(prepareTaskForm({ ...values, title: 'Новое название' }, context)).toMatchObject({
      errors: {},
      request: { title: 'Новое название', pinned_start: originalTask.pinned_start },
    })
    expect(prepareTaskForm(values, { ...context, originalTask: undefined }).request).toBeNull()
  })

  it('requires a future start when the duration of an already started pinned task changes', () => {
    const values = taskToFormValues(originalTask, context.timezone)
    expect(prepareTaskForm({ ...values, durationMin: 90 }, context).errors.pinnedStartLocal).toBe(
      'Выберите время в будущем.',
    )
  })

  it('preserves an unchanged expired deadline but rejects a newly entered past deadline', () => {
    const task = DAILY_SCHEDULE_FIXTURES.normal.tasks[2]
    const values = taskToFormValues(task, context.timezone)
    expect(
      prepareTaskForm({ ...values, title: 'Новое название' }, { ...context, originalTask: task })
        .errors,
    ).toEqual({})
    expect(
      prepareTaskForm(
        { ...values, deadlineLocal: '2026-11-12T14:00' },
        { ...context, originalTask: task },
      ).errors.deadlineLocal,
    ).toBe('Выберите время в будущем.')
  })

  it('preserves the exact original instant when its displayed time repeats during DST', () => {
    const task = {
      ...DAILY_SCHEDULE_FIXTURES.normal.tasks[2],
      planned_date: '2026-10-25',
      deadline: '2026-10-25T01:30:00Z',
      preferred_start: null,
    }
    const values = taskToFormValues(task, 'Europe/Berlin')
    expect(values.deadlineLocal).toBe('2026-10-25T02:30')
    expect(
      prepareTaskForm(values, { ...context, timezone: 'Europe/Berlin', originalTask: task }).request
        ?.deadline,
    ).toBe(task.deadline.replace('Z', '.000Z'))
  })

  it.each<TaskFormOptions>([
    { recurrence: null, reminderMinutes: null },
    {
      recurrence: { frequency: 'daily', interval: 1, weekdays: [], until: null },
      reminderMinutes: 0,
    },
    {
      recurrence: { frequency: 'weekly', interval: 1, weekdays: [3], until: null },
      reminderMinutes: 5,
    },
    {
      recurrence: { frequency: 'weekly', interval: 2, weekdays: [1, 3, 5], until: '2026-12-30' },
      reminderMinutes: 30,
    },
  ])('retains recurrence and reminder settings when prefilling the form: %j', (options) => {
    expect(
      prepareTaskSettings(taskOptionsToSettings(options, '2026-11-11'), '2026-11-11').options,
    ).toEqual(options)
  })
})
