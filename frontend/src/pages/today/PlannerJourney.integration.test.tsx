import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { createQueryClient } from '@/shared/api/queryClient'
import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { planningDetails, savedFixture } from '@/test/planningDetails'
import type { Task } from '@/shared/model/task'
import type { SavedSchedule } from '@/shared/model/schedule'
import { useSessionStore } from '@/stores/session'
import { TodayPage } from './TodayPage'
import { NewTaskPage } from './NewTaskPage'
import { TaskPage } from './TaskPage'

vi.mock('./TodayCriticalDays', () => ({ TodayCriticalDays: () => null }))
vi.mock('./TodayEnergyProfile', () => ({ TodayEnergyProfile: () => null }))

const fixture = DAILY_SCHEDULE_FIXTURES.normal
const title = 'Проверить сквозной сценарий'
const taskId = '10000000-0000-4000-8000-000000000099'
const error = (code: string, status = 409) =>
  Response.json({ error: { code, message: code } }, { status })

function setup({ overloaded = false, lostCreation = false } = {}) {
  useSessionStore.getState().signIn({
    accessToken: 'journey-token',
    user: {
      name: 'Анна',
      birthDate: '2000-01-01',
      chronotype: 'lark',
      workStart: '08:00',
      workEnd: overloaded ? '10:00' : '18:00',
    },
  })
  useSessionStore.setState({ timezone: fixture.timezone, isOnboarded: true })
  const state = { tasks: [] as Task[], saved: null as SavedSchedule | null }
  const request = vi.fn<typeof fetch>(async (input, init) => {
    const url = new URL(String(input))
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : {}
    if (url.pathname.endsWith('/schedule/replan')) {
      if (body.schedule_version !== (state.saved?.version ?? 0))
        return error('SCHEDULE_VERSION_CONFLICT')
      state.saved!.version++
      state.tasks = state.tasks.map((task) => ({ ...task, version: task.version + 1 }))
      return Response.json({ schedule: state.saved })
    }
    if (url.pathname.endsWith('/schedule/details'))
      return state.saved
        ? Response.json(planningDetails(state.saved))
        : error('SCHEDULE_NOT_FOUND', 404)
    if (url.pathname.endsWith('/schedule'))
      return state.saved ? Response.json(state.saved) : error('SCHEDULE_NOT_FOUND', 404)
    if (url.pathname.endsWith('/tasks') && method === 'GET')
      return Response.json({ items: state.tasks, total: state.tasks.length, limit: 100, offset: 0 })
    if (url.pathname.endsWith('/tasks') && method === 'POST') {
      const task: Task = {
        ...fixture.tasks[2],
        ...body,
        id: taskId,
        version: 2,
        status: overloaded ? 'pending' : 'scheduled',
        is_pinned: false,
        pinned_start: null,
        actual_start: null,
        completed_at: null,
        preferred_start: null,
      }
      state.tasks.push(task)
      state.saved = {
        ...savedFixture(fixture),
        version: 1,
        slots: overloaded
          ? []
          : [
              {
                ...fixture.slots[0],
                task_id: taskId,
                kind: 'task',
                start_at: '2026-11-11T05:00:00Z',
                end_at: '2026-11-11T05:30:00Z',
                is_pinned: false,
                reason_codes: ['ENERGY_RANKED'],
                explanation: 'Время выбрано по свободному окну.',
              },
            ],
        unscheduled: overloaded
          ? [{ task_id: taskId, reason_codes: ['NO_FEASIBLE_INTERVAL'] }]
          : [],
        metrics: {
          requested_min: task.duration_min,
          planned_min: overloaded ? 0 : task.duration_min,
          capacity_min: overloaded ? 120 : 600,
          high_intensity_min: 0,
          critical_level: 0,
          load_factor: 1,
          moved_min: 0,
        },
      }
      if (lostCreation) throw new TypeError('Response lost after commit')
      return Response.json(task, { status: 201 })
    }
    const task = state.tasks.find((task) => url.pathname.includes(`/tasks/${task.id}`))
    if (!task) return error('TASK_NOT_FOUND', 404)
    if (method === 'GET') return Response.json(task)
    if (body.version !== task.version) return error('TASK_VERSION_CONFLICT')
    if (url.pathname.endsWith('/pin')) {
      if (body.schedule_versions?.[fixture.date] !== state.saved!.version)
        return error('SCHEDULE_VERSION_CONFLICT')
      task.is_pinned = true
      task.pinned_start = body.start_at
      state.saved!.slots = state.saved!.slots.map((slot) => ({ ...slot, is_pinned: true }))
    } else if (url.pathname.endsWith('/complete')) {
      task.status = 'done'
      task.completed_at = '2026-11-11T05:30:00Z'
    } else if (url.pathname.endsWith('/reopen')) {
      task.status = 'scheduled'
      task.completed_at = null
    } else throw new Error(`Unexpected write: ${method} ${url.pathname}`)
    task.version++
    state.saved!.version++
    return Response.json(task)
  })
  vi.stubGlobal('fetch', request)
  const client = createQueryClient()
  const router = createMemoryRouter(
    [
      {
        path: '/today',
        element: <TodayPage />,
        children: [
          { path: 'new', element: <NewTaskPage /> },
          { path: 'tasks/:taskId', element: <TaskPage /> },
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
  const writes = () => request.mock.calls.filter(([, init]) => init?.method === 'POST')
  return { state, client, router, writes }
}

async function create(duration = 30) {
  await screen.findByText('На сегодня задач нет')
  await userEvent.click(screen.getAllByRole('button', { name: 'Добавить задачу' })[0])
  await userEvent.type(await screen.findByRole('textbox', { name: 'Название' }), title)
  await userEvent.click(screen.getByRole('radio', { name: 'Рутина' }))
  if (duration === 30) await userEvent.click(screen.getByRole('radio', { name: '30 мин' }))
  else {
    await userEvent.click(screen.getByRole('radio', { name: 'Другое…' }))
    await userEvent.type(screen.getByLabelText('Длительность в минутах'), String(duration))
  }
  await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
}

describe('planner journey across creation, dashboard and task routes', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-11T04:42:00Z'))
  })
  afterEach(() => vi.useRealTimers())

  it('creates from an empty day, places, pins, replans, completes and reopens with fresh versions', async () => {
    const { state, client, router, writes } = setup()
    await create()
    await screen.findByText('Задача добавлена')
    await userEvent.click(screen.getByRole('button', { name: 'Открыть' }))
    const panel = await screen.findByRole('dialog', { name: title })
    await waitFor(() =>
      expect(within(panel).getByRole('button', { name: 'Закрепить' })).toBeEnabled(),
    )
    expect(panel).toHaveTextContent('10:00–10:30')
    await userEvent.click(within(panel).getByRole('button', { name: 'Закрепить' }))
    await within(panel).findByText('Время закреплено')
    await userEvent.keyboard('{Escape}')
    const replan = screen.getByRole('button', { name: 'Перепланировать' })
    await waitFor(() => expect(replan).toBeEnabled())
    await userEvent.click(replan)
    await screen.findByText('План и нагрузка обновлены.')
    await act(async () => router.navigate(`/today/tasks/${taskId}`))
    const refreshed = await screen.findByRole('dialog', { name: title })
    await waitFor(() =>
      expect(within(refreshed).getByRole('button', { name: 'Открепить' })).toBeEnabled(),
    )
    await userEvent.click(within(refreshed).getByRole('button', { name: 'Выполнить' }))
    await within(refreshed).findByText('Задача выполнена')
    await userEvent.keyboard('{Escape}')
    await userEvent.type(screen.getByRole('searchbox'), title)
    await userEvent.click(await screen.findByRole('button', { name: new RegExp(title) }))
    await userEvent.click(await screen.findByRole('button', { name: 'Вернуть в работу' }))
    await screen.findByText('Задача возвращена в работу')
    expect(state.tasks[0]).toMatchObject({
      status: 'scheduled',
      completed_at: null,
      is_pinned: true,
    })
    expect(state.saved!.slots[0]).toMatchObject({
      start_at: '2026-11-11T05:00:00Z',
      is_pinned: true,
    })
    expect(writes().map(([url]) => new URL(String(url)).pathname.split('/').at(-1))).toEqual([
      'tasks',
      'pin',
      'replan',
      'complete',
      'reopen',
    ])
    expect(JSON.parse(String(writes()[1][1]?.body))).toMatchObject({
      version: 2,
      schedule_versions: { [fixture.date]: 1 },
    })
    expect(JSON.parse(String(writes()[2][1]?.body))).toEqual({
      planned_date: fixture.date,
      schedule_version: 2,
      allow_date_change: false,
    })
    expect(JSON.parse(String(writes()[3][1]?.body))).toEqual({ version: 4 })
    expect(JSON.parse(String(writes()[4][1]?.body))).toEqual({ version: 5 })
    client.clear()
  })

  it('keeps an unplaced task visible with its server reason after an overloaded creation', async () => {
    const { client, writes } = setup({ overloaded: true })
    await create(480)
    await screen.findByText('Задача добавлена')
    const unplaced = await screen.findByRole('region', { name: 'Без времени' })
    expect(unplaced).toHaveTextContent(title)
    await waitFor(() =>
      expect(unplaced).toHaveTextContent('Не найдено непрерывного окна нужной длительности'),
    )
    await userEvent.click(within(unplaced).getByRole('button'))
    expect(await screen.findByRole('dialog', { name: title })).toHaveTextContent(
      'Время не назначено',
    )
    expect(
      await screen.findByRole('region', { name: 'Почему задача без времени' }),
    ).toHaveTextContent('Дата задачи сохранена')
    expect(writes()).toHaveLength(1)
    client.clear()
  })

  it('finds a committed task after a lost creation response without submitting it twice', async () => {
    const { client, writes } = setup({ lostCreation: true })
    await create()
    expect(await screen.findByRole('alert')).toHaveTextContent('Задача могла сохраниться')
    expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue(title)
    await userEvent.keyboard('{Escape}')
    const timeline = await screen.findByRole('list', { name: 'Интервалы расписания' })
    expect(within(timeline).getByRole('button', { name: new RegExp(title) })).toBeInTheDocument()
    expect(writes()).toHaveLength(1)
    client.clear()
  })
})
