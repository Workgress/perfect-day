import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { HttpError } from './http'
import { apiProblem } from './errors'
import {
  completeTask,
  createTask,
  deleteTask,
  getTask,
  getTasks,
  reopenTask,
  skipTask,
  updateTask,
  pinTask,
  moveTask,
  unpinTask,
  startTask,
} from './tasks'

const task = DAILY_SCHEDULE_FIXTURES.normal.tasks[2]
const body = {
  title: 'Экзамен',
  type: 'intellectual' as const,
  duration_min: 90,
  planned_date: '2026-11-19',
}

function respond(value: unknown, status = 200) {
  const fetchMock = vi.fn<typeof fetch>(async () => Response.json(value, { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('task API contract', () => {
  it('sends only the public creation payload and keeps the returned version and timestamps', async () => {
    const request = respond(task, 201)
    expect(await createTask(body)).toEqual(task)
    const [url, init] = request.mock.calls[0]
    expect(new URL(String(url)).pathname).toBe('/api/v1/tasks')
    expect(init).toMatchObject({ method: 'POST', body: JSON.stringify(body) })
  })

  it.each([
    { preferred_start: null },
    { is_pinned: false },
    { pinned_start: null },
    { status: 'done' },
    { reminder: 5 },
    { recurrence: null },
  ])('rejects unsupported creation fields before sending %j', async (extra) => {
    const request = respond(task)
    await expect(createTask({ ...body, ...extra })).rejects.toThrow('API задач не поддерживает')
    expect(request).not.toHaveBeenCalled()
  })

  it('sends PATCH omissions and explicit nulls unchanged, with the original version', async () => {
    const request = respond({ ...task, description: null, deadline: null, version: 8 })
    const patch = { version: 7, description: null, deadline: null }
    expect((await updateTask(task.id, patch)).version).toBe(8)
    expect(request.mock.calls[0][1]).toMatchObject({ method: 'PATCH', body: JSON.stringify(patch) })
  })

  it('rejects an empty patch and read-only placement updates', async () => {
    const request = respond(task)
    await expect(updateTask(task.id, { version: 1 })).rejects.toThrow('изменённое поле')
    const patch = { version: 1, title: 'Название', is_pinned: true }
    await expect(updateTask(task.id, patch)).rejects.toThrow('API задач не поддерживает')
    expect(request).not.toHaveBeenCalled()
  })

  it('reads a task without a browser cache', async () => {
    const request = respond(task)
    expect(await getTask(task.id)).toEqual(task)
    expect(String(request.mock.calls[0][0])).toContain(`/tasks/${task.id}`)
    expect(request.mock.calls[0][1]?.cache).toBe('no-store')
  })

  it('preserves the inclusive date range and pagination, including an empty page with total', async () => {
    const page = { items: [], total: 4, limit: 10, offset: 20 }
    const request = respond(page)
    expect(
      await getTasks({
        from: '2026-11-18',
        to: '2026-11-20',
        type: 'routine',
        limit: 10,
        offset: 20,
      }),
    ).toEqual(page)
    expect(Object.fromEntries(new URL(String(request.mock.calls[0][0])).searchParams)).toEqual({
      from: '2026-11-18',
      to: '2026-11-20',
      type: 'routine',
      limit: '10',
      offset: '20',
    })
  })

  it.each([
    [completeTask, 'complete'],
    [skipTask, 'skip'],
    [reopenTask, 'reopen'],
  ] as const)('uses a separate versioned status command %#', async (command, name) => {
    const request = respond(task)
    await command(task.id, 7)
    expect(String(request.mock.calls[0][0])).toContain(`/tasks/${task.id}/${name}`)
    expect(request.mock.calls[0][1]).toMatchObject({ method: 'POST', body: '{"version":7}' })
  })

  it('handles DELETE 204 without parsing JSON and passes version in the query', async () => {
    const request = vi.fn<typeof fetch>(async () => new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', request)
    await expect(deleteTask(task.id, 7)).resolves.toBeUndefined()
    expect(new URL(String(request.mock.calls[0][0])).searchParams.get('version')).toBe('7')
    expect(request.mock.calls[0][1]?.method).toBe('DELETE')
  })

  it.each([
    [pinTask, 'pin'],
    [moveTask, 'move'],
  ] as const)('sends exact placement versions and timestamps for %s', async (command, name) => {
    const request = respond(task)
    const placement = {
      planned_date: '2026-11-12',
      start_at: '2026-11-12T10:05:00+05:00',
      version: 7,
      schedule_versions: { '2026-11-11': 3, '2026-11-12': 0 },
    }
    const controller = new AbortController()
    await command(task.id, placement, controller.signal)
    expect(new URL(String(request.mock.calls[0][0])).pathname).toBe(
      `/api/v1/tasks/${task.id}/${name}`,
    )
    expect(request.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify(placement),
      signal: controller.signal,
    })
  })

  it('reads the unpin response and sends both versions as query parameters without a body', async () => {
    const request = respond({ ...task, is_pinned: false, pinned_start: null, version: 9 })
    expect((await unpinTask(task.id, 7, 3)).version).toBe(9)
    expect(Object.fromEntries(new URL(String(request.mock.calls[0][0])).searchParams)).toEqual({
      version: '7',
      schedule_version: '3',
    })
    expect(request.mock.calls[0][1]?.method).toBe('DELETE')
    expect(request.mock.calls[0][1]?.body).toBeUndefined()
  })

  it('starts with the server clock, preserving actual_start and date lock from the response', async () => {
    const updated = { ...task, actual_start: '2026-11-11T04:42:17Z', is_date_locked: true }
    const request = respond(updated)
    const body = { version: 7, schedule_versions: { '2026-11-11': 3 } }
    expect(await startTask(task.id, body)).toEqual(updated)
    expect(String(request.mock.calls[0][0])).toContain('/start-now')
    expect(request.mock.calls[0][1]?.body).toBe(JSON.stringify(body))
  })

  it.each([409, 422, 503])(
    'preserves server error details without retrying a write: %s',
    async (status) => {
      const problem = {
        code: status === 409 ? 'TASK_VERSION_CONFLICT' : 'VALIDATION_ERROR',
        message: 'Ошибка',
        details: {
          fields: [
            {
              field: 'body.deadline',
              code: 'DEADLINE_BEFORE_PLANNED_DATE',
              message: 'Проверьте срок',
            },
          ],
        },
      }
      const request = respond({ error: problem }, status)
      const error = await createTask(body).catch((error) => error)
      expect(error).toBeInstanceOf(HttpError)
      expect(error.status).toBe(status)
      expect(apiProblem(error)).toEqual(problem)
      expect(request).toHaveBeenCalledTimes(1)
    },
  )

  it.each([
    null,
    { ...task, version: 0 },
    { ...task, created_at: undefined },
    { ...task, deadline: '2026-11-19' },
    { ...task, type: 'social' },
    { ...task, actual_start: '2026-11-11T10:00:00' },
    { ...task, actual_start: undefined },
    { ...task, is_date_locked: 'false' },
  ])('rejects an invalid task response %#', async (value) => {
    respond(value)
    await expect(getTask(task.id)).rejects.toThrow('некорректные данные')
  })

  it('passes cancellation to fetch', async () => {
    const request = respond(task)
    const controller = new AbortController()
    await getTask(task.id, controller.signal)
    expect(request.mock.calls[0][1]?.signal).toBe(controller.signal)
  })

  it('does not turn a network failure into a success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('offline')
      }),
    )
    await expect(createTask(body)).rejects.toThrow('offline')
  })
})
