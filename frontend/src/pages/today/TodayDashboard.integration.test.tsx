import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { createQueryClient } from '@/shared/api/queryClient'
import { scheduleKeys, taskKeys } from '@/shared/api/planningKeys'
import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { createBiorhythmDemoPoints } from '@/shared/fixtures/biorhythms'
import { useSessionStore } from '@/stores/session'
import { TodayPage } from './TodayPage'
import { TaskPage, EditTaskPage } from './TaskPage'

const fixture = DAILY_SCHEDULE_FIXTURES.normal

function setup(
  options: {
    bioError?: boolean
    timezone?: string
    overloaded?: boolean
    noCandidate?: boolean
  } = {},
) {
  useSessionStore.getState().signIn({
    accessToken: 'dashboard-token',
    user: {
      name: 'Анна',
      birthDate: '2003-09-20',
      chronotype: 'lark',
      workStart: '08:00',
      workEnd: options.overloaded ? '17:00' : '18:00',
    },
  })
  useSessionStore.setState({ timezone: fixture.timezone, isOnboarded: true })
  const state = {
    tasks: structuredClone(fixture.tasks),
    saved: {
      id: fixture.schedule!.id,
      planned_date: fixture.date,
      timezone: fixture.timezone,
      version: 1,
      algorithm_version: 'test',
      generated_at: new Date().toISOString(),
      slots: fixture.slots.map((slot) => ({ ...slot, reason_codes: [] })),
      unscheduled: [],
      warnings: [],
      moves: [],
      metrics: {
        requested_min: 390,
        planned_min: 390,
        capacity_min: 600,
        high_intensity_min: 180,
        critical_level: 0,
        load_factor: 1,
        moved_min: 0,
      },
    },
    bioError: options.bioError ?? false,
    transferConflict: false,
    transferWait: undefined as Promise<void> | undefined,
  }
  if (options.overloaded) {
    state.tasks[5].type = 'creative'
    const meeting = {
      ...state.tasks[5],
      id: '10000000-0000-4000-8000-000000000098',
      title: 'Рабочая встреча',
      type: 'routine' as const,
      priority: 'high' as const,
    }
    state.tasks.push(meeting)
    state.saved.slots.push({
      ...state.saved.slots[2],
      id: '20000000-0000-4000-8000-000000000098',
      task_id: meeting.id,
      kind: 'task',
      start_at: '2026-11-11T07:00:00Z',
      end_at: '2026-11-11T08:00:00Z',
    })
  }
  if (options.noCandidate)
    state.tasks = state.tasks.map((task) => ({ ...task, deadline: '2026-11-11T18:00:00Z' }))
  const request = vi.fn<typeof fetch>(async (input, init) => {
    const url = new URL(String(input))
    if (url.pathname.endsWith('/biorhythms')) {
      if (state.bioError)
        return Response.json(
          { error: { code: 'INTERNAL_ERROR', message: 'Ошибка биоритмов' } },
          { status: 500 },
        )
      const from = url.searchParams.get('from')!
      const to = url.searchParams.get('to')!
      return Response.json({
        start: from,
        end: to,
        step: 'day',
        period: null,
        timezone: options.timezone ?? fixture.timezone,
        algorithm_version: 'test',
        points: createBiorhythmDemoPoints(from, to),
      })
    }
    if (url.pathname.endsWith('/critical-days'))
      return Response.json({
        start: url.searchParams.get('from'),
        end: url.searchParams.get('to'),
        timezone: fixture.timezone,
        algorithm_version: 'test',
        days: [
          {
            date: '2026-11-12',
            level: 1,
            kind: 'single',
            crossings: [{ cycle: 'physical', at: '2026-11-12T10:00:00+05:00' }],
          },
          {
            date: '2026-11-30',
            level: 1,
            kind: 'single',
            crossings: [{ cycle: 'intellectual', at: '2026-11-30T10:00:00+05:00' }],
          },
        ].filter(
          (day) =>
            day.date >= url.searchParams.get('from')! && day.date <= url.searchParams.get('to')!,
        ),
      })
    if (url.pathname.endsWith('/schedule')) return Response.json(state.saved)
    if (url.pathname.endsWith('/tasks')) {
      const tasks = state.tasks.filter((task) => task.planned_date === url.searchParams.get('date'))
      return Response.json({ items: tasks, total: tasks.length, offset: 0, limit: 100 })
    }
    const actionTask = state.tasks.find((item) => url.pathname.includes(`/tasks/${item.id}/`))
    if (actionTask && (url.pathname.endsWith('/pin') || url.pathname.endsWith('/start-now'))) {
      await state.transferWait
      const body = init?.body ? JSON.parse(String(init.body)) : {}
      const updated = { ...actionTask, version: actionTask.version + 1 }
      if (url.pathname.endsWith('/pin')) {
        updated.is_pinned = init?.method !== 'DELETE'
        updated.pinned_start = updated.is_pinned ? body.start_at : null
      } else updated.actual_start = new Date().toISOString()
      state.tasks = state.tasks.map((item) => (item.id === updated.id ? updated : item))
      state.saved.slots = state.saved.slots.map((slot) =>
        slot.task_id === updated.id
          ? {
              ...slot,
              is_pinned: updated.is_pinned,
              ...(updated.actual_start
                ? {
                    start_at: updated.actual_start,
                    end_at: new Date(
                      Date.parse(updated.actual_start) + updated.duration_min * 60_000,
                    ).toISOString(),
                  }
                : {}),
            }
          : slot,
      )
      state.saved.version++
      return Response.json(updated)
    }
    const task = state.tasks.find((item) => url.pathname.endsWith(`/${item.id}`))
    if (task && init?.method === 'PATCH') {
      await state.transferWait
      if (state.transferConflict)
        return Response.json(
          { error: { code: 'TASK_VERSION_CONFLICT', message: 'Задача изменилась' } },
          { status: 409 },
        )
      const body = JSON.parse(String(init.body))
      const updated = { ...task, planned_date: body.planned_date, version: task.version + 1 }
      state.tasks = state.tasks.map((item) => (item.id === task.id ? updated : item))
      state.saved.slots = state.saved.slots.filter((slot) => slot.task_id !== task.id)
      state.saved.version++
      return Response.json(updated)
    }
    if (task && (!init?.method || init.method === 'GET')) return Response.json(task)
    throw new Error(`Unexpected request: ${url.pathname}`)
  })
  vi.stubGlobal('fetch', request)
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
      { path: '/biorhythms', element: <p>Прогноз открыт</p> },
    ],
    { initialEntries: ['/today'] },
  )
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { client, router, request, state }
}

describe('assembled Today dashboard', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-11T04:42:00Z'))
  })
  afterEach(() => vi.useRealTimers())

  it('pins, unpins and starts directly from the nearest task card and refreshes the dashboard', async () => {
    const { client, state, request } = setup()
    const summary = () => screen.getByRole('complementary', { name: 'Сводка дня' })
    await screen.findByRole('list', { name: 'Интервалы расписания' })
    await userEvent.click(within(summary()).getByRole('button', { name: 'Закрепить' }))
    await screen.findByText('Время закреплено')
    expect(state.tasks[2].is_pinned).toBe(true)
    await userEvent.click(within(summary()).getByRole('button', { name: 'Открепить' }))
    await screen.findByText('Время откреплено')
    await userEvent.click(within(summary()).getByRole('button', { name: 'Начать' }))
    await waitFor(() =>
      expect(within(summary()).getByRole('button', { name: 'Задача начата' })).toBeDisabled(),
    )
    expect(state.tasks[2].actual_start).toBe('2026-11-11T04:42:00.000Z')
    const writes = request.mock.calls.filter(([, init]) => init?.method && init.method !== 'GET')
    expect(writes).toHaveLength(3)
    expect(JSON.parse(String(writes[0][1]?.body))).toEqual({
      planned_date: fixture.date,
      start_at: fixture.slots.find((slot) => slot.task_id === fixture.tasks[2].id)!.start_at,
      version: 1,
      schedule_versions: { [fixture.date]: 1 },
    })
    expect(Object.fromEntries(new URL(String(writes[1][0])).searchParams)).toEqual({
      version: '2',
      schedule_version: '2',
    })
    expect(JSON.parse(String(writes[2][1]?.body))).toEqual({
      version: 3,
      schedule_versions: { [fixture.date]: 3 },
    })
    client.clear()
  })

  it('combines three API charts, warning, real load and next task with panel and editing routes', async () => {
    const { client, router, request } = setup()
    await screen.findByRole('list', { name: 'Интервалы расписания' })
    const energy = await screen.findByRole('region', {
      name: /Энергетический профиль на сегодня/,
    })
    expect(within(energy).getAllByRole('img')).toHaveLength(3)
    expect(energy).toHaveTextContent('Рассчитан по дате рождения 20.09.2003 · день 8 453')
    expect(energy).toHaveTextContent('Подготовка к экзамену — в окне 10:00–11:30.')
    expect(
      within(energy).getByRole('article', { name: 'Интеллектуальный цикл' }),
    ).toHaveTextContent(/Критический день — .*30 ноября/)
    expect(energy).not.toHaveTextContent('Классическая модель биоритмов.')
    expect(screen.getByRole('region', { name: /Впереди критический день/ })).toBeInTheDocument()
    const plan = screen.getByRole('region', { name: 'План на день' })
    const critical = screen.getByRole('region', { name: /Впереди критический день/ })
    expect(plan.compareDocumentPosition(energy) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(energy.compareDocumentPosition(critical) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    const summary = screen.getByRole('complementary', { name: 'Сводка дня' })
    expect(within(summary).getByText('Далее через 18 минут')).toBeInTheDocument()
    expect(
      within(summary).getByRole('img', { name: 'Нагрузка: 420 из 600 минут, 70 %' }),
    ).toBeInTheDocument()
    const bioRequest = request.mock.calls.find(([url]) =>
      new URL(String(url)).pathname.endsWith('/biorhythms'),
    )!
    expect(new Headers(bioRequest[1]?.headers).get('Authorization')).toBe('Bearer dashboard-token')
    await userEvent.click(within(summary).getByRole('link', { name: 'Подготовка к экзамену' }))
    expect(await screen.findByRole('dialog', { name: 'Подготовка к экзамену' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Изменить' }))
    expect(await screen.findByRole('dialog', { name: 'Редактировать задачу' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe(`/today/tasks/${fixture.tasks[2].id}/edit`)
    client.clear()
  })

  it('keeps the timeline and summary usable when the charts fail, and retries independently', async () => {
    const { client, state } = setup({ bioError: true })
    await screen.findByRole('list', { name: 'Интервалы расписания' })
    expect(screen.getByRole('complementary', { name: 'Сводка дня' })).toHaveTextContent(
      'Подготовка к экзамену',
    )
    expect(screen.queryByRole('img', { name: /Физический цикл/ })).not.toBeInTheDocument()
    state.bioError = false
    await userEvent.click(screen.getByRole('button', { name: 'Повторить загрузку биоритмов' }))
    expect(await screen.findByRole('img', { name: /Физический цикл/ })).toBeInTheDocument()
    client.clear()
  })

  it('expands the real load breakdown and reserve with keyboard controls, then collapses it', async () => {
    const { client } = setup()
    await screen.findByRole('list', { name: 'Интервалы расписания' })
    const load = screen.getByRole('region', { name: /^Нагрузка/ })
    const toggle = within(load).getByRole('button', { name: /^Нагрузка/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(
      within(load).queryByRole('list', { name: 'Нагрузка по типам задач' }),
    ).not.toBeInTheDocument()
    toggle.focus()
    await userEvent.keyboard('{Enter}')
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(load).toHaveTextContent('из 10 ч рабочего окна · запас 3 ч')
    const legend = within(load).getByRole('list', { name: 'Нагрузка по типам задач' })
    expect(legend).toHaveTextContent('Интеллектуальная 2 ч 30 мин')
    expect(legend).toHaveTextContent('Физическая 1 ч')
    expect(legend).toHaveTextContent('Творческая 1 ч')
    expect(legend).toHaveTextContent('Рутина 1 ч 30 мин')
    expect(legend).toHaveTextContent('Отдых 1 ч')
    expect(load).toHaveTextContent('Загрузка показывает долю задач в рабочем окне.')
    expect(load).not.toHaveTextContent('доступного времени')
    await userEvent.keyboard(' ')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(
      within(load).queryByRole('list', { name: 'Нагрузка по типам задач' }),
    ).not.toBeInTheDocument()
    client.clear()
  })

  it('updates the nearest task and load from the same refreshed schedule and follows the profile clock', async () => {
    const { client, state } = setup()
    await screen.findByRole('list', { name: 'Интервалы расписания' })
    const summary = screen.getByRole('complementary', { name: 'Сводка дня' })
    state.tasks[2].status = 'done'
    state.saved.metrics.planned_min = 300
    state.saved.slots = state.saved.slots.filter((slot) => slot.task_id !== state.tasks[2].id)
    const generation = useSessionStore.getState().generation
    await act(async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: taskKeys.day(generation, fixture.date) }),
        client.invalidateQueries({ queryKey: scheduleKeys.day(generation, fixture.date) }),
      ])
    })
    await waitFor(() =>
      expect(screen.getByRole('complementary', { name: 'Сводка дня' })).not.toHaveTextContent(
        'Подготовка к экзамену',
      ),
    )
    expect(
      screen.getByRole('img', { name: 'Нагрузка: 330 из 600 минут, 55 %' }),
    ).toBeInTheDocument()
    await act(async () => {
      vi.setSystemTime(new Date('2026-11-11T17:00:00Z'))
      fireEvent.focus(window)
    })
    expect(screen.getByRole('complementary', { name: 'Сводка дня' })).toHaveTextContent(
      'На сегодня больше нет запланированных задач.',
    )
    expect(summary).not.toHaveTextContent('Далее через 18 минут')
    client.clear()
  })

  it('rejects graph data from another timezone without hiding the plan', async () => {
    const { client } = setup({ timezone: 'UTC' })
    await screen.findByRole('list', { name: 'Интервалы расписания' })
    expect(
      await screen.findByRole('button', { name: 'Повторить загрузку биоритмов' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: /Физический цикл/ })).not.toBeInTheDocument()
    client.clear()
  })

  it('opens the week forecast from the energy profile', async () => {
    const { client, router } = setup()
    await userEvent.click(screen.getByRole('link', { name: 'Графики и прогноз' }))
    expect(router.state.location.pathname).toBe('/biorhythms')
    expect(router.state.location.search).toBe('?period=week&date=2026-11-11')
    client.clear()
  })

  it('offers a move with a warning on overload and leaves the plan unchanged when dismissed', async () => {
    const { client, request } = setup({ overloaded: true })
    await screen.findByRole('list', { name: 'Интервалы расписания' })
    const load = screen.getByRole('region', { name: /^Нагрузка/ })
    expect(load).toHaveTextContent('Можно разгрузить день')
    expect(load).toHaveTextContent('Перенести «Оформить список литературы»')
    expect(load).toHaveTextContent('Так сегодня освободится 1 ч.')
    expect(load).toHaveTextContent('Свободное время на выбранный день ещё не подтверждено.')
    await userEvent.click(within(load).getByRole('button', { name: 'Оставить' }))
    expect(load).toHaveTextContent('Сегодняшний план оставлен без изменений.')
    expect(request.mock.calls.filter(([, init]) => init?.method === 'PATCH')).toHaveLength(0)
    client.clear()
  })

  it('moves only the explicitly selected task once and refreshes the daily schedule', async () => {
    const { client, state, request } = setup({ overloaded: true })
    await screen.findByRole('list', { name: 'Интервалы расписания' })
    const task = state.tasks[5]
    let finish!: () => void
    state.transferWait = new Promise<void>((resolve) => {
      finish = resolve
    })
    const move = screen.getByRole('button', { name: /^Перенести на/ })
    await userEvent.click(move)
    expect(move).toBeDisabled()
    await userEvent.click(move)
    await act(async () => {
      finish()
    })
    await screen.findByText(`«${task.title}» (Творческая, 1 ч) перенесена на 12 ноября.`)
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /^Перенести на/ })).not.toBeInTheDocument(),
    )
    const writes = request.mock.calls.filter(([, init]) => init?.method === 'PATCH')
    expect(writes).toHaveLength(1)
    expect(JSON.parse(String(writes[0][1]?.body))).toEqual({
      version: task.version,
      planned_date: '2026-11-12',
    })
    expect(state.tasks.find((item) => item.id === task.id)?.planned_date).toBe('2026-11-12')
    client.clear()
  })

  it('refreshes a version conflict without automatically retrying the move', async () => {
    const { client, state, request } = setup({ overloaded: true })
    await screen.findByRole('list', { name: 'Интервалы расписания' })
    state.transferConflict = true
    state.tasks[5].version++
    await userEvent.click(screen.getByRole('button', { name: /^Перенести на/ }))
    expect(
      await screen.findByText('Задача изменилась. Проверьте актуальный план перед переносом.'),
    ).toBeInTheDocument()
    await screen.findByRole('list', { name: 'Интервалы расписания' })
    expect(request.mock.calls.filter(([, init]) => init?.method === 'PATCH')).toHaveLength(1)
    client.clear()
  })

  it('does not propose a task whose deadline cannot accommodate tomorrow', async () => {
    const { client } = setup({ overloaded: true, noCandidate: true })
    await screen.findByRole('list', { name: 'Интервалы расписания' })
    expect(
      screen.getByText(
        /Подходящей задачи для переноса на завтра без нарушения дедлайна не найдено/,
      ),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Перенести на/ })).not.toBeInTheDocument()
    client.clear()
  })
})
