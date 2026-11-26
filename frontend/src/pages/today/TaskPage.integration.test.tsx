import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { createQueryClient } from '@/shared/api/queryClient'
import { taskKeys, scheduleKeys } from '@/shared/api/planningKeys'
import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { localDate } from '@/shared/lib/dateTime'
import { useSessionStore } from '@/stores/session'
import type { Task } from '@/shared/model/task'
import { TaskPage, EditTaskPage } from './TaskPage'
import { TodayPage } from './TodayPage'

vi.mock('./TodayTimeline', () => ({ TodayTimeline: () => null }))
vi.mock('./useTodaySchedule', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./useTodaySchedule')>()),
  useTodaySchedule: () => ({ version: undefined }),
}))
vi.mock('./TodayCriticalDays', () => ({ TodayCriticalDays: () => null }))
vi.mock('./TodayEnergyProfile', () => ({ TodayEnergyProfile: () => null }))

const task = (): Task => ({
  ...DAILY_SCHEDULE_FIXTURES.normal.tasks[3],
  planned_date: localDate(new Date(), 'Asia/Yekaterinburg'),
  deadline: null,
  is_pinned: false,
  pinned_start: null,
  preferred_start: null,
  status: 'pending' as const,
  version: 3,
})
const failure = (code: string, status = 409, details = {}) =>
  Response.json({ error: { code, message: code, details } }, { status })
function setup(edit = false) {
  useSessionStore.getState().signIn({
    accessToken: 'test-token',
    user: {
      name: 'Анна',
      birthDate: '2003-09-20',
      chronotype: 'lark',
      workStart: '08:00',
      workEnd: '18:00',
    },
  })
  useSessionStore.setState({ timezone: 'Asia/Yekaterinburg', isOnboarded: true })
  const generation = useSessionStore.getState().generation
  const client = createQueryClient()
  const router = createMemoryRouter(
    [
      {
        path: '/today',
        element: <TodayPage />,
        children: [
          { path: 'tasks/:taskId', element: <TaskPage /> },
          { path: 'tasks/:taskId/edit', element: <EditTaskPage /> },
        ],
      },
      { path: '/other', element: <p>Другой экран</p> },
    ],
    { initialEntries: [`/today/tasks/${task().id}${edit ? '/edit' : ''}`] },
  )
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { client, router, generation }
}
async function rename() {
  const title = await screen.findByRole('textbox', { name: 'Название' })
  await userEvent.clear(title)
  await userEvent.type(title, 'Мой черновик')
}
function mockApi(write: (init: RequestInit) => Response | Promise<Response>, read = () => task()) {
  const request = vi.fn<typeof fetch>(async (url, init) => {
    if (String(url).includes('/schedule')) return failure('SCHEDULE_NOT_FOUND', 404)
    if (!init?.method || init.method === 'GET') return Response.json(read())
    return write(init)
  })
  vi.stubGlobal('fetch', request)
  return request
}
const writes = (request: ReturnType<typeof mockApi>) =>
  request.mock.calls.filter(([, init]) => init?.method && init.method !== 'GET')

describe('saved tasks with the API', () => {
  it.each(['network', '503'])(
    'keeps edited values and avoids an automatic retry after a failed save (%s)',
    async (mode) => {
      const request = mockApi(() => {
        if (mode === 'network') throw new TypeError('Failed to fetch')
        return failure('SERVICE_UNAVAILABLE', 503)
      })
      const { client, router } = setup(true)
      await rename()
      await userEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))
      await screen.findByRole('alert')
      expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue('Мой черновик')
      expect(router.state.location.pathname).toContain('/edit')
      expect(writes(request)).toHaveLength(1)
      client.clear()
    },
  )

  it('keeps the task panel open and does not announce deletion after a network failure', async () => {
    const request = mockApi(() => {
      throw new TypeError('Failed to fetch')
    })
    const { client, router } = setup()
    await userEvent.click(await screen.findByRole('button', { name: 'Удалить задачу' }))
    await screen.findByText('Нет связи с сервером. Проверьте подключение и повторите попытку.')
    expect(router.state.location.pathname).toBe(`/today/tasks/${task().id}`)
    expect(screen.queryByText('Задача удалена')).not.toBeInTheDocument()
    expect(writes(request)).toHaveLength(1)
    client.clear()
  })

  it('sends only changed fields and invalidates lists and schedules after saving', async () => {
    const request = mockApi((init) =>
      Response.json({ ...task(), ...JSON.parse(String(init.body)), version: 7 }),
    )
    const { client, generation, router } = setup(true)
    const listKey = taskKeys.list(generation, { date: task().planned_date })
    const scheduleKey = scheduleKeys.day(generation, '2099-01-01')
    client.setQueryData(listKey, { items: [task()] })
    client.setQueryData(scheduleKey, { version: 1 })
    await rename()
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))
    await waitFor(() => expect(router.state.location.pathname).toBe(`/today/tasks/${task().id}`))
    expect(JSON.parse(String(writes(request)[0][1]?.body))).toEqual({
      title: 'Мой черновик',
      version: 3,
    })
    expect(client.getQueryState(listKey)?.isInvalidated).toBe(true)
    expect(client.getQueryState(scheduleKey)?.isInvalidated).toBe(true)
    client.clear()
  })

  it('preserves the draft on conflict and explicitly retries only the user delta with the fresh version', async () => {
    let version = 3
    let count = 0
    const request = mockApi(
      (init) => {
        if (++count === 1) {
          version = 8
          return failure('TASK_VERSION_CONFLICT')
        }
        return Response.json({
          ...task(),
          description: 'Чужое изменение',
          ...JSON.parse(String(init.body)),
          version: 9,
        })
      },
      () => ({
        ...task(),
        title: count >= 2 ? 'Мой черновик' : task().title,
        version,
        description: version === 8 ? 'Чужое изменение' : task().description,
      }),
    )
    const { client } = setup(true)
    await rename()
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))
    await screen.findByText(/Задача изменилась\. Актуальная версия/)
    expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue('Мой черновик')
    expect(writes(request)).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить мои изменения' }))
    await waitFor(() => expect(writes(request)).toHaveLength(2))
    expect(JSON.parse(String(writes(request)[1][1]?.body))).toEqual({
      title: 'Мой черновик',
      version: 8,
    })
    await screen.findByRole('heading', { name: 'Мой черновик' })
    client.clear()
  })

  it('can discard the draft explicitly and load the current server task', async () => {
    let changed = false
    mockApi(
      () => {
        changed = true
        return failure('TASK_VERSION_CONFLICT')
      },
      () => ({
        ...task(),
        title: changed ? 'Актуальная задача' : task().title,
        version: changed ? 8 : 3,
      }),
    )
    const { client } = setup(true)
    await rename()
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))
    await userEvent.click(
      await screen.findByRole('button', {
        name: 'Загрузить актуальную задачу и сбросить черновик',
      }),
    )
    expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue('Актуальная задача')
    expect(screen.getByRole('button', { name: 'Сохранить изменения' })).toBeDisabled()
    client.clear()
  })

  it('keeps the draft and blocks saving when the conflicting task was deleted', async () => {
    let reads = 0
    const request = vi.fn<typeof fetch>(async (_url, init) => {
      if (init?.method === 'PATCH') return failure('TASK_VERSION_CONFLICT')
      return ++reads === 1 ? Response.json(task()) : failure('TASK_NOT_FOUND', 404)
    })
    vi.stubGlobal('fetch', request)
    const { client } = setup(true)
    await rename()
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))
    await screen.findByText(/Задача удалена\. Черновик/)
    expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue('Мой черновик')
    expect(screen.getByRole('button', { name: 'Сохранить изменения' })).toBeDisabled()
    client.clear()
  })

  it('maps server validation errors without clearing edited values', async () => {
    mockApi(() =>
      failure('VALIDATION_ERROR', 422, {
        fields: [{ field: 'body.title', message: 'Такое название не подходит' }],
      }),
    )
    const { client } = setup(true)
    await rename()
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))
    await screen.findByText('Такое название не подходит')
    expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue('Мой черновик')
    client.clear()
  })

  it('deletes with one click and closes after 204', async () => {
    const request = mockApi(() => new Response(null, { status: 204 }))
    const { client, router } = setup()
    await userEvent.click(await screen.findByRole('button', { name: 'Удалить задачу' }))
    await screen.findByText('Задача удалена')
    expect(router.state.location.pathname).toBe('/today')
    expect(writes(request)[0][1]?.method).toBe('DELETE')
    expect(String(writes(request)[0][0])).toContain('version=3')
    client.clear()
  })

  it('refreshes a conflicting deletion without replaying the command', async () => {
    let changed = false
    const request = mockApi(
      () => {
        changed = true
        return failure('TASK_VERSION_CONFLICT')
      },
      () => ({ ...task(), version: changed ? 8 : 3 }),
    )
    const { client } = setup()
    await userEvent.click(await screen.findByRole('button', { name: 'Удалить задачу' }))
    await screen.findByText(/Данные обновлены/)
    expect(writes(request)).toHaveLength(1)
    client.clear()
  })
  it('prevents duplicate saves and closing while pending; ignores results after an account change', async () => {
    let resolve!: (value: Response) => void
    const pending = new Promise<Response>((done) => {
      resolve = done
    })
    const request = mockApi(() => pending)
    const { client, router, generation } = setup(true)
    await rename()
    const form = screen.getByRole('form', { name: 'Редактирование задачи' })
    fireEvent.submit(form)
    fireEvent.submit(form)
    await waitFor(() => expect(writes(request)).toHaveLength(1))
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(router.state.location.pathname).toContain('/edit')
    await act(async () => {
      useSessionStore.getState().signOut()
      resolve(Response.json({ ...task(), title: 'Мой черновик', version: 4 }))
      await pending
    })
    expect(writes(request)).toHaveLength(1)
    expect(writes(request)[0][1]?.signal?.aborted).toBe(true)
    expect(client.getQueryData(taskKeys.detail(generation, task().id))).not.toMatchObject({
      version: 4,
    })
    client.clear()
  })

  it('shows a missing task without an editable fallback', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => failure('TASK_NOT_FOUND', 404)),
    )
    const { client } = setup(true)
    await screen.findByText('Задача удалена или недоступна.')
    expect(screen.queryByRole('textbox', { name: 'Название' })).not.toBeInTheDocument()
    client.clear()
  })
})
