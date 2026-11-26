import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import type { Task } from '@/shared/model/task'
import { savedFixture, planningDetails } from '@/test/planningDetails'
import { placeCreatedTask } from './placeCreatedTask'

const day = DAILY_SCHEDULE_FIXTURES.normal
const created: Task = {
  ...day.tasks[2],
  status: 'pending',
  is_pinned: false,
  pinned_start: null,
  is_date_locked: false,
  deadline: null,
}
const failure = (code: string, status = 409) =>
  Response.json({ error: { code, message: code } }, { status })
function mockPlacement(
  options: {
    lost?: boolean
    blocked?: boolean
    readError?: boolean
    scheduleError?: boolean
    deadline?: boolean
  } = {},
) {
  const before = { ...savedFixture(day), version: 6 }
  const after = {
    ...before,
    version: 7,
    moves: [
      {
        task_id: created.id,
        from_date: day.date,
        to_date: '2026-11-12',
        reason_code: 'NO_AVAILABLE_TIME',
      },
    ],
  }
  const task =
    options.deadline || options.blocked
      ? created
      : {
          ...created,
          planned_date: '2026-11-12',
          status: 'scheduled' as const,
          version: created.version + 1,
        }
  const request = vi.fn<typeof fetch>(async (input) => {
    const url = new URL(String(input))
    if (url.pathname.endsWith('/replan')) {
      if (options.lost) throw new TypeError('Failed to fetch')
      if (options.blocked) return failure('SCHEDULE_VERSION_CONFLICT')
      return Response.json({ schedule: after })
    }
    if (url.pathname.endsWith('/details')) {
      const schedule = {
        ...after,
        moves: [],
        unscheduled: [{ task_id: created.id, reason_codes: ['DEADLINE_EXCEEDED'] }],
      }
      return Response.json(
        planningDetails(schedule, {
          unscheduled_explanations: [
            {
              task_id: created.id,
              planned_date: day.date,
              reason_codes: ['DEADLINE_EXCEEDED'],
              explanation: 'До дедлайна не осталось подходящих интервалов.',
            },
          ],
        }),
      )
    }
    if (url.pathname.endsWith('/schedule'))
      return options.scheduleError ? failure('SERVICE_UNAVAILABLE', 503) : Response.json(before)
    if (options.readError) throw new TypeError('Failed to fetch')
    return Response.json(task)
  })
  vi.stubGlobal('fetch', request)
  return request
}

describe('automatic placement after creation', () => {
  it('allows date changes only for the creation fallback and returns the actual task with an explanation', async () => {
    const request = mockPlacement()
    const result = await placeCreatedTask(created, day.timezone, new AbortController().signal)
    expect(result.task.planned_date).toBe('2026-11-12')
    expect(result.explanation).toContain('В выбранный день не нашлось подходящего окна')
    expect(result.explanation).toContain('12.11.2026')
    const writes = request.mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(writes).toHaveLength(1)
    expect(JSON.parse(String(writes[0][1]?.body))).toEqual({
      planned_date: day.date,
      schedule_version: 6,
      allow_date_change: true,
    })
    expect(
      request.mock.calls.some(([url]) => new URL(String(url)).pathname.endsWith('/tasks')),
    ).toBe(false)
  })
  it.each(['scheduled', 'done', 'skipped'] as const)(
    'does not replan an already %s task',
    async (status) => {
      const request = mockPlacement()
      expect(
        await placeCreatedTask({ ...created, status }, day.timezone, new AbortController().signal),
      ).toEqual({ task: { ...created, status } })
      expect(request).not.toHaveBeenCalled()
    },
  )
  it.each([{ is_pinned: true }, { is_date_locked: true }])(
    'respects explicit placement constraints %j',
    async (constraint) => {
      const request = mockPlacement()
      await placeCreatedTask(
        { ...created, ...constraint },
        day.timezone,
        new AbortController().signal,
      )
      expect(request).not.toHaveBeenCalled()
    },
  )
  it('reconciles a lost replan response without another command', async () => {
    const request = mockPlacement({ lost: true })
    expect(
      (await placeCreatedTask(created, day.timezone, new AbortController().signal)).task
        .planned_date,
    ).toBe('2026-11-12')
    expect(request.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  })
  it('keeps the committed task and reports a conflict without replaying creation or replanning', async () => {
    const request = mockPlacement({ blocked: true })
    const result = await placeCreatedTask(created, day.timezone, new AbortController().signal)
    expect(result.task).toEqual(created)
    expect(result.explanation).toContain(
      'Задача создана, но автоматическое размещение не подтверждено',
    )
    expect(request.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  })
  it('shows the server deadline explanation when no permitted future day fits', async () => {
    mockPlacement({ deadline: true })
    const result = await placeCreatedTask(
      { ...created, deadline: `${day.date}T13:00:00Z` },
      day.timezone,
      new AbortController().signal,
    )
    expect(result.task.status).toBe('pending')
    expect(result.explanation).toBe('До дедлайна не осталось подходящих интервалов.')
  })
  it('does not submit a guessed version after a failed schedule read', async () => {
    const request = mockPlacement({ scheduleError: true, blocked: true })
    const result = await placeCreatedTask(created, day.timezone, new AbortController().signal)
    expect(result.explanation).toContain('не подтверждено')
    expect(request.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  })
  it('preserves creation success when the result cannot be read', async () => {
    mockPlacement({ readError: true })
    const result = await placeCreatedTask(created, day.timezone, new AbortController().signal)
    expect(result.task).toEqual(created)
    expect(result.explanation).toContain('Создавать её повторно не нужно')
  })
  it('aborts placement when the account changes', async () => {
    const controller = new AbortController()
    const request = mockPlacement()
    controller.abort()
    await expect(placeCreatedTask(created, day.timezone, controller.signal)).rejects.toMatchObject({
      name: 'AbortError',
    })
    expect(request).not.toHaveBeenCalled()
  })
})
