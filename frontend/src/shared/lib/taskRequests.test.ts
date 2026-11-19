import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { prepareTaskForm, taskToFormValues } from '@/pages/today/taskFormModel'
import { taskCreateRequest, taskUpdateRequest, UnsupportedTaskPlacementError } from './taskRequests'

const task = DAILY_SCHEDULE_FIXTURES.normal.tasks[3]
const context = {
  timezone: 'Asia/Yekaterinburg',
  workStart: '08:00',
  workEnd: '18:00',
  now: new Date('2026-11-11T04:42:00Z'),
  originalTask: task,
}
const draft = () => prepareTaskForm(taskToFormValues(task, context.timezone), context).request!

describe('form draft to public task requests', () => {
  it('removes read-only placement defaults from creation requests', () => {
    expect(taskCreateRequest(draft())).toEqual({
      title: task.title,
      description: task.description,
      type: task.type,
      priority: task.priority,
      duration_min: task.duration_min,
      planned_date: task.planned_date,
      deadline: new Date(task.deadline!).toISOString(),
    })
  })

  it('converts a local deadline using the profile timezone rather than the browser timezone', () => {
    const prepared = prepareTaskForm(
      { ...taskToFormValues(task, context.timezone), deadlineLocal: '2026-11-11T18:00' },
      context,
    ).request!
    expect(taskCreateRequest(prepared).deadline).toBe('2026-11-11T13:00:00.000Z')
  })

  it('returns only changed fields and keeps explicit nulls and the original version', () => {
    expect(taskUpdateRequest({ ...draft(), description: null, deadline: null }, task)).toEqual({
      description: null,
      deadline: null,
      version: task.version,
    })
    expect(taskUpdateRequest(draft(), task)).toBeNull()
  })

  it('does not mistake equivalent timestamp formatting for a deadline change', () => {
    expect(taskUpdateRequest({ ...draft(), title: 'Новое название' }, task)).toEqual({
      title: 'Новое название',
      version: task.version,
    })
  })

  it('does not silently discard an unsupported placement selection', () => {
    expect(() => taskCreateRequest({ ...draft(), preferred_start: '10:00:00' })).toThrow(
      UnsupportedTaskPlacementError,
    )
    expect(() =>
      taskCreateRequest({ ...draft(), is_pinned: true, pinned_start: '2026-11-11T05:00:00Z' }),
    ).toThrow(UnsupportedTaskPlacementError)
    expect(() => taskUpdateRequest({ ...draft(), preferred_start: '10:00:00' }, task)).toThrow(
      UnsupportedTaskPlacementError,
    )
  })

  it('allows editing a pinned task without writing its read-only placement fields', () => {
    const fixture = DAILY_SCHEDULE_FIXTURES.normal.tasks[4]
    const pinned = { ...fixture, pinned_start: fixture.pinned_start!.replace('.000Z', 'Z') }
    const prepared = prepareTaskForm(
      { ...taskToFormValues(pinned, context.timezone), title: 'Новое название' },
      { ...context, originalTask: pinned },
    ).request!
    expect(taskUpdateRequest(prepared, pinned)).toEqual({
      title: 'Новое название',
      version: pinned.version,
    })
  })
})
