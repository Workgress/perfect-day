import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { createQueryClient } from '@/shared/api/queryClient'
import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { localDate } from '@/shared/lib/dateTime'
import type { SavedSchedule } from '@/shared/model/schedule'
import type { Task } from '@/shared/model/task'
import { useSessionStore } from '@/stores/session'
import { TodayPage } from './TodayPage'
import { NewTaskPage } from './NewTaskPage'
import { TaskPage, EditTaskPage } from './TaskPage'
vi.mock('./TodayCriticalDays', () => ({ TodayCriticalDays: () => null }))
vi.mock('./TodayEnergyProfile', () => ({ TodayEnergyProfile: () => null }))

const timezone = 'Asia/Yekaterinburg'
const fixture = DAILY_SCHEDULE_FIXTURES.normal
const failed = (code: string, status = 500) =>
  Response.json({ error: { code, message: code } }, { status })

function data() {
  const date = localDate(new Date(), timezone)
  const delta = Date.parse(`${date}T00:00:00Z`) - Date.parse(`${fixture.date}T00:00:00Z`)
  const shift = (value: string | null) =>
    value ? new Date(Date.parse(value) + delta).toISOString() : null
  const tasks = fixture.tasks.map((task) => ({
    ...task,
    planned_date: date,
    deadline: shift(task.deadline),
    completed_at: shift(task.completed_at),
    pinned_start: shift(task.pinned_start),
  }))
  const saved: SavedSchedule = {
    id: fixture.schedule!.id,
    planned_date: date,
    timezone,
    version: 1,
    algorithm_version: 'test-api',
    generated_at: new Date().toISOString(),
    slots: fixture.slots.map((slot) => ({
      ...slot,
      start_at: shift(slot.start_at)!,
      end_at: shift(slot.end_at)!,
      reason_codes: [],
    })),
    unscheduled: [],
    metrics: {
      requested_min: 390,
      planned_min: 390,
      capacity_min: 600,
      high_intensity_min: 180,
      critical_level: 0,
      load_factor: 1,
      moved_min: 0,
    },
    warnings: [],
    moves: [],
  }
  return { tasks, saved, date }
}

function setup() {
  useSessionStore.getState().signIn({
    accessToken: 'today-token',
    user: {
      name: 'Анна',
      birthDate: '2003-09-20',
      chronotype: 'lark',
      workStart: '08:00',
      workEnd: '18:00',
    },
  })
  useSessionStore.setState({ timezone, isOnboarded: true })
  const client = createQueryClient()
  const router = createMemoryRouter(
    [
      {
        path: '/today',
        element: <TodayPage />,
        children: [
          { path: 'new', element: <NewTaskPage /> },
          { path: 'tasks/:taskId', element: <TaskPage /> },
          { path: 'tasks/:taskId/edit', element: <EditTaskPage /> },
        ],
      },
    ],
    { initialEntries: ['/today'] },
  )
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { client, router }
}

function api(
  state: ReturnType<typeof data>,
  options: {
    scheduleError?: string
    listError?: boolean
    missing?: Set<string>
    pageSize?: number
  } = {},
) {
  const request = vi.fn<typeof fetch>(async (url, init) => {
    const path = new URL(String(url))
    const method = init?.method ?? 'GET'
    if (path.pathname.endsWith('/schedule'))
      return options.scheduleError
        ? failed(options.scheduleError, options.scheduleError === 'SCHEDULE_NOT_FOUND' ? 404 : 500)
        : Response.json(state.saved)
    if (path.pathname.endsWith('/tasks') && method === 'GET') {
      if (options.listError) return failed('TASK_LIST_FAILED')
      const limit = options.pageSize ?? Number(path.searchParams.get('limit') ?? 50)
      const offset = Number(path.searchParams.get('offset') ?? 0)
      const tasks = state.tasks.filter(
        (task) =>
          !options.missing?.has(task.id) && task.planned_date === path.searchParams.get('date'),
      )
      return Response.json({
        items: tasks.slice(offset, offset + limit),
        total: tasks.length,
        limit,
        offset,
      })
    }
    if (path.pathname.endsWith('/tasks') && method === 'POST') {
      const task: Task = {
        ...state.tasks[2],
        ...JSON.parse(String(init?.body)),
        id: '10000000-0000-4000-8000-000000000099',
        preferred_start: null,
        is_pinned: false,
        pinned_start: null,
        version: 2,
        status: 'scheduled',
      }
      state.tasks.push(task)
      state.saved = {
        ...state.saved,
        version: state.saved.version + 1,
        slots: [
          ...state.saved.slots,
          {
            id: '20000000-0000-4000-8000-000000000099',
            task_id: task.id,
            kind: 'task',
            start_at: `${state.date}T17:00:00+05:00`,
            end_at: `${state.date}T17:30:00+05:00`,
            explanation: 'Реальное свободное окно',
            reason_codes: [],
            is_pinned: false,
          },
        ],
      }
      return Response.json(task, { status: 201 })
    }
    const task = state.tasks.find(
      (item) => item.id === decodeURIComponent(path.pathname.split('/').at(-1)!),
    )
    if (!task) return failed('TASK_NOT_FOUND', 404)
    if (method === 'PATCH') {
      Object.assign(task, JSON.parse(String(init?.body)), { version: task.version + 1 })
      if (task.planned_date !== state.date)
        state.saved.slots = state.saved.slots.filter((slot) => slot.task_id !== task.id)
      state.saved.version++
    }
    if (method === 'DELETE') {
      state.tasks = state.tasks.filter((item) => item.id !== task.id)
      state.saved = {
        ...state.saved,
        version: state.saved.version + 1,
        slots: state.saved.slots.filter((slot) => slot.task_id !== task.id),
      }
      return new Response(null, { status: 204 })
    }
    return Response.json(task)
  })
  vi.stubGlobal('fetch', request)
  return request
}

async function ready() {
  return screen.findByRole('list', { name: 'Интервалы расписания' })
}

describe('today with the saved schedule API', () => {
  it('searches loaded day tasks, opens a result and restores the timeline with Escape', async () => {
    api(data())
    const { client, router } = setup()
    await ready()
    const input = screen.getByRole('searchbox', { name: 'Поиск задач текущего дня' })
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    expect(input).toHaveFocus()
    await userEvent.type(input, '  ЭКЗАМЕНУ  ')
    const results = screen.getByRole('region', { name: 'Результаты поиска задач' })
    expect(within(results).getByRole('status')).toHaveTextContent('Найдено: 1')
    expect(screen.queryByRole('list', { name: 'Интервалы расписания' })).not.toBeInTheDocument()
    await userEvent.click(within(results).getByRole('button', { name: /Подготовка к экзамену/ }))
    expect(await screen.findByRole('dialog', { name: 'Подготовка к экзамену' })).toBeInTheDocument()
    expect(router.state.location.pathname).toContain(data().tasks[2].id)
    await userEvent.keyboard('{Escape}')
    input.focus()
    await userEvent.keyboard('{Escape}')
    expect(input).toHaveValue('')
    await ready()
    await userEvent.type(input, 'несуществующая задача')
    expect(screen.getByRole('status')).toHaveTextContent('На этот день ничего не найдено.')
    expect(screen.getByRole('button', { name: 'Перепланировать' })).toBeDisabled()
    client.clear()
  })

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-20T04:42:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads every task page, renders server slots in profile timezone and opens a selected task', async () => {
    const state = data()
    const request = api(state, { pageSize: 2 })
    const { router, client } = setup()
    const list = await ready()
    const task = within(list).getByRole('button', { name: /^Подготовка к экзамену\. 10:00–11:30/ })
    expect(
      request.mock.calls.filter(([url]) => new URL(String(url)).pathname.endsWith('/tasks')),
    ).toHaveLength(4)
    const query = new URL(String(request.mock.calls[0][0]))
    expect(query.searchParams.get('date')).toBe(state.date)
    expect(new Headers(request.mock.calls[0][1]?.headers).get('Authorization')).toBe(
      'Bearer today-token',
    )
    await userEvent.click(task)
    expect(await screen.findByRole('dialog', { name: 'Подготовка к экзамену' })).toBeInTheDocument()
    expect(router.state.location.pathname).toContain(state.tasks[2].id)
    await userEvent.keyboard('{Escape}')
    expect(router.state.location.pathname).toBe('/today')
    client.clear()
  })

  it('fetches referenced tasks missing from the date list before rendering the timeline', async () => {
    const state = data()
    const request = api(state, { missing: new Set([state.tasks[2].id]) })
    const { client } = setup()
    expect(
      within(await ready()).getByRole('button', { name: /^Подготовка к экзамену\./ }),
    ).toBeInTheDocument()
    expect(request.mock.calls.some(([url]) => String(url).endsWith(`/${state.tasks[2].id}`))).toBe(
      true,
    )
    client.clear()
  })

  it('keeps tasks without a saved schedule visible without inventing slots', async () => {
    const state = data()
    api(state, { scheduleError: 'SCHEDULE_NOT_FOUND' })
    const { client } = setup()
    await screen.findByText('Расписание на этот день ещё не сохранено')
    expect(screen.queryByRole('list', { name: 'Интервалы расписания' })).not.toBeInTheDocument()
    expect(
      within(screen.getByRole('region', { name: 'Задачи на этот день' })).getByRole('button', {
        name: /Подготовка к экзамену/,
      }),
    ).toBeInTheDocument()
    client.clear()
  })

  it('rejects an incomplete schedule referencing a deleted task and recovers after refresh', async () => {
    const state = data()
    state.tasks = state.tasks.filter((task) => task.id !== fixture.tasks[2].id)
    api(state)
    const { client } = setup()
    expect(await screen.findByRole('alert')).toHaveTextContent('TASK_NOT_FOUND')
    expect(screen.queryByRole('list', { name: 'Интервалы расписания' })).not.toBeInTheDocument()
    state.saved.slots = state.saved.slots.filter((slot) => slot.task_id !== fixture.tasks[2].id)
    await userEvent.click(screen.getByRole('button', { name: 'Повторить загрузку плана' }))
    await ready()
    client.clear()
  })

  it('stops inconsistent task pagination instead of displaying duplicate or incomplete data', async () => {
    const state = data()
    const request = vi.fn<typeof fetch>(async (url) => {
      const query = new URL(String(url))
      if (query.pathname.endsWith('/schedule')) return Response.json(state.saved)
      const offset = Number(query.searchParams.get('offset') ?? 0)
      return Response.json({ items: [state.tasks[0]], total: state.tasks.length, limit: 1, offset })
    })
    vi.stubGlobal('fetch', request)
    const { client } = setup()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Список задач изменился во время загрузки',
    )
    expect(request.mock.calls.filter(([url]) => String(url).includes('/tasks?'))).toHaveLength(2)
    expect(screen.queryByRole('list', { name: 'Интервалы расписания' })).not.toBeInTheDocument()
    client.clear()
  })

  it('distinguishes a saved empty day from a missing schedule', async () => {
    const state = data()
    state.tasks = []
    state.saved.slots = []
    api(state)
    const { client } = setup()
    await ready()
    expect(screen.getByText('На сегодня задач нет')).toBeInTheDocument()
    expect(screen.queryByText('Расписание на этот день ещё не сохранено')).not.toBeInTheDocument()
    client.clear()
  })

  it('restores the empty timeline and day windows when there are no tasks and no saved plan', async () => {
    const state = data()
    state.tasks = []
    api(state, { scheduleError: 'SCHEDULE_NOT_FOUND' })
    const { client } = setup()
    await ready()
    expect(screen.getByText('На сегодня задач нет')).toBeInTheDocument()
    expect(screen.getByText('08:00')).toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'Окна сегодня' })).toHaveTextContent(
      '10:00–12:00 · сложная учёба',
    )
    expect(screen.queryByRole('complementary', { name: 'Сводка дня' })).not.toBeInTheDocument()
    expect(screen.queryByText('Расписание на этот день ещё не сохранено')).not.toBeInTheDocument()
    await userEvent.click(
      within(screen.getByRole('region', { name: 'План на день' })).getByRole('button', {
        name: 'Добавить задачу',
      }),
    )
    expect(await screen.findByRole('dialog', { name: 'Новая задача' })).toBeInTheDocument()
    client.clear()
  })

  it('does not treat a schedule failure as an empty day', async () => {
    const state = data()
    state.tasks = []
    api(state, { scheduleError: 'PLANNER_UNAVAILABLE' })
    const { client } = setup()
    expect(await screen.findByRole('alert')).toHaveTextContent('PLANNER_UNAVAILABLE')
    expect(screen.queryByText('На сегодня задач нет')).not.toBeInTheDocument()
    client.clear()
  })

  it('keeps unplaced and completed tasks available through search without footer lists', async () => {
    const state = data()
    state.saved.slots = []
    state.tasks[2] = { ...state.tasks[2], status: 'pending' }
    state.saved.unscheduled = [{ task_id: state.tasks[2].id, reason_codes: ['NO_CAPACITY'] }]
    api(state)
    const { client } = setup()
    await ready()
    expect(screen.queryByText(/^Время расписания:/)).not.toBeInTheDocument()
    expect(screen.queryByText('Все интервалы списком')).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Без времени' })).not.toBeInTheDocument()
    expect(
      screen.queryByRole('region', { name: 'Выполненные и пропущенные' }),
    ).not.toBeInTheDocument()
    const search = screen.getByRole('searchbox', { name: 'Поиск задач текущего дня' })
    await userEvent.type(search, 'экзамену')
    expect(screen.getByRole('button', { name: /Подготовка к экзамену/ })).toBeInTheDocument()
    await userEvent.clear(search)
    await userEvent.type(search, 'Разобрать почту')
    expect(screen.getByRole('button', { name: /Разобрать почту/ })).toBeInTheDocument()
    client.clear()
  })

  it.each(['schedule', 'tasks'] as const)(
    'shows a recoverable %s error without a fake timeline',
    async (source) => {
      const state = data()
      const options = {
        scheduleError: source === 'schedule' ? 'SCHEDULE_FAILED' : undefined,
        listError: source === 'tasks',
      }
      const request = api(state, options)
      const { client } = setup()
      await screen.findByRole('alert')
      expect(screen.queryByRole('list', { name: 'Интервалы расписания' })).not.toBeInTheDocument()
      options.scheduleError = undefined
      options.listError = false
      await userEvent.click(screen.getByRole('button', { name: 'Повторить загрузку плана' }))
      await ready()
      expect(request.mock.calls.filter(([url]) => String(url).includes('/schedule'))).toHaveLength(
        2,
      )
      client.clear()
    },
  )

  it('rejects a saved timezone different from profile work clocks', async () => {
    const state = data()
    state.saved.timezone = 'UTC'
    api(state)
    const { client } = setup()
    expect(await screen.findByRole('alert')).toHaveTextContent('другом часовом поясе')
    expect(screen.queryByRole('list', { name: 'Интервалы расписания' })).not.toBeInTheDocument()
    client.clear()
  })

  it('uses the profile date across UTC midnight and changes days when the tab is focused', async () => {
    vi.setSystemTime(new Date('2026-11-20T18:59:00Z'))
    const state = data()
    const request = api(state, { scheduleError: 'SCHEDULE_NOT_FOUND' })
    const { client } = setup()
    await screen.findByText('Расписание на этот день ещё не сохранено')
    state.tasks = []
    vi.setSystemTime(new Date('2026-11-20T19:01:00Z'))
    fireEvent(window, new Event('focus'))
    await waitFor(() =>
      expect(
        request.mock.calls.some(
          ([url]) => new URL(String(url)).searchParams.get('date') === '2026-11-21',
        ),
      ).toBe(true),
    )
    client.clear()
  })

  it('removes a task from today after its date is changed in the editor', async () => {
    const state = data()
    const task = state.tasks[3]
    const request = api(state)
    const { client } = setup()
    await userEvent.click(
      within(await ready()).getByRole('button', { name: new RegExp(`^${task.title}\\.`) }),
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Изменить' }))
    const target = new Date(`${state.date}T12:00:00Z`)
    target.setUTCDate(target.getUTCDate() + 1)
    const targetDate = target.toISOString().slice(0, 10)
    fireEvent.change(await screen.findByLabelText('День задачи'), { target: { value: targetDate } })
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))
    await screen.findByRole('dialog', { name: task.title })
    await ready()
    expect(state.tasks.find((item) => item.id === task.id)?.planned_date).toBe(targetDate)
    expect(
      within(await ready()).queryByRole('button', { name: new RegExp(`^${task.title}\\.`) }),
    ).not.toBeInTheDocument()
    const patch = request.mock.calls.find(([, init]) => init?.method === 'PATCH')!
    expect(JSON.parse(String(patch[1]?.body))).toMatchObject({ planned_date: targetDate })
    client.clear()
  })

  it.each(['Рутина', 'Физическая', 'Творческая', 'Интеллектуальная'])(
    'refreshes the timeline after creating, editing and immediately deleting a task (%s)',
    async (type) => {
      const state = data()
      api(state)
      const { client } = setup()
      await ready()
      await userEvent.click(screen.getByRole('button', { name: 'Добавить задачу' }))
      await userEvent.type(
        await screen.findByRole('textbox', { name: 'Название' }),
        'Новая задача из API',
      )
      await userEvent.click(screen.getByRole('radio', { name: type }))
      await userEvent.click(screen.getByRole('radio', { name: '30 мин' }))
      await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
      await screen.findByText('Задача добавлена')
      await userEvent.click(
        within(await ready()).getByRole('button', { name: /^Новая задача из API\./ }),
      )
      await screen.findByRole('dialog', { name: 'Новая задача из API' })
      await userEvent.click(screen.getByRole('button', { name: 'Изменить' }))
      const title = await screen.findByRole('textbox', { name: 'Название' })
      await userEvent.clear(title)
      await userEvent.type(title, 'Обновлённая задача')
      await userEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))
      await screen.findByRole('dialog', { name: 'Обновлённая задача' })
      await userEvent.click(screen.getByRole('button', { name: 'Удалить задачу' }))
      await screen.findByText('Задача удалена')
      expect(
        within(await ready()).queryByRole('button', { name: /^Обновлённая задача\./ }),
      ).not.toBeInTheDocument()
      client.clear()
    },
    15000,
  )

  it('does not display a previous account response after the session changes', async () => {
    let resolve!: (response: Response) => void
    const pending = new Promise<Response>((done) => {
      resolve = done
    })
    const state = data()
    const request = vi.fn<typeof fetch>(async (url) =>
      String(url).includes('/schedule') ? failed('SCHEDULE_NOT_FOUND', 404) : pending,
    )
    vi.stubGlobal('fetch', request)
    const { client } = setup()
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2))
    await act(async () => {
      useSessionStore.getState().signOut()
      resolve(
        Response.json({ items: state.tasks, total: state.tasks.length, limit: 100, offset: 0 }),
      )
      await pending
    })
    expect(screen.queryByText('Подготовка к экзамену')).not.toBeInTheDocument()
    expect(request.mock.calls[0][1]?.signal?.aborted).toBe(true)
    client.clear()
  })
})
