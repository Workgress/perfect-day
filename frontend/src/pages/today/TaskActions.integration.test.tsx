import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { onlineManager, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { createQueryClient } from '@/shared/api/queryClient'
import { scheduleKeys, taskKeys } from '@/shared/api/planningKeys'
import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { useSessionStore } from '@/stores/session'
import type { Task } from '@/shared/model/task'
import { TaskPage } from './TaskPage'

const fixture = DAILY_SCHEDULE_FIXTURES.normal
const failure = (code: string, status = 409, message = code) =>
  Response.json({ error: { code, message } }, { status })

function setup(
  options: {
    absent?: boolean
    scheduleFailure?: boolean
    unplaced?: boolean
    explanation?: string
    pinned?: boolean
  } = {},
) {
  useSessionStore.getState().signIn({
    accessToken: 'actions-token',
    user: { name: 'Анна', birthDate: '2003-09-20', chronotype: 'lark' },
  })
  useSessionStore.setState({ timezone: fixture.timezone, isOnboarded: true })
  const generation = useSessionStore.getState().generation
  const state = {
    task: {
      ...fixture.tasks[2],
      version: 3,
      actual_start: null,
      is_pinned: options.pinned ?? false,
      pinned_start: options.pinned ? '2026-11-11T05:00:00Z' : null,
    } as Task,
    absent: options.absent ?? false,
    scheduleFailure: options.scheduleFailure ?? false,
    commandError: '',
    commandMessage: '',
    failRead: false,
    offline: false,
    loseResponse: false,
    wait: undefined as Promise<void> | undefined,
    scheduleVersion: 6,
    start: '2026-11-11T05:00:00Z',
  }
  const saved = (date: string) => ({
    id: fixture.schedule!.id,
    planned_date: date,
    timezone: fixture.timezone,
    version: date === state.task.planned_date ? state.scheduleVersion : 4,
    algorithm_version: 'test',
    generated_at: '2026-11-11T04:00:00Z',
    slots: options.unplaced
      ? []
      : [
          {
            ...fixture.slots.find((slot) => slot.task_id === state.task.id)!,
            ...(options.explanation ? { explanation: options.explanation } : {}),
            start_at: state.start,
            end_at: new Date(Date.parse(state.start) + 90 * 60_000).toISOString(),
            is_pinned: state.task.is_pinned,
            reason_codes: [],
          },
        ],
    unscheduled: [],
    metrics: {
      requested_min: 90,
      planned_min: 90,
      capacity_min: 600,
      high_intensity_min: 90,
      critical_level: 0,
      load_factor: 1,
      moved_min: 0,
    },
    warnings: [],
    moves: [],
  })
  const request = vi.fn<typeof fetch>(async (input, init) => {
    if (state.offline) throw new TypeError('Offline')
    const url = new URL(String(input))
    if (url.pathname.endsWith('/schedule')) {
      if (state.scheduleFailure) return failure('PLANNER_UNAVAILABLE', 503)
      if (state.absent) return failure('SCHEDULE_NOT_FOUND', 404)
      return Response.json(saved(url.searchParams.get('date')!))
    }
    if (!init?.method || init.method === 'GET')
      return state.failRead ? failure('SERVICE_UNAVAILABLE', 503) : Response.json(state.task)
    await state.wait
    if (state.commandError) {
      state.task = { ...state.task, version: 8 }
      state.scheduleVersion = 9
      return failure(state.commandError, 409, state.commandMessage || state.commandError)
    }
    const command = url.pathname.split('/').at(-1)
    const body = init.body ? JSON.parse(String(init.body)) : {}
    const task = { ...state.task, version: state.task.version + 1 }
    if (command === 'pin' && init.method === 'DELETE') {
      task.is_pinned = false
      task.pinned_start = null
    }
    if (command === 'move' || (command === 'pin' && init.method === 'POST')) {
      task.is_pinned = true
      task.pinned_start = body.start_at
      task.planned_date = body.planned_date
      state.start = body.start_at
    }
    if (command === 'start-now') {
      task.actual_start = '2026-11-11T04:42:17Z'
      state.start = task.actual_start
    }
    if (command === 'complete') {
      task.status = 'done'
      task.completed_at = '2026-11-11T06:00:00Z'
    }
    if (command === 'skip') {
      task.status = 'skipped'
      task.completed_at = null
    }
    if (command === 'reopen') {
      task.status = 'scheduled'
      task.actual_start = null
      task.completed_at = null
    }
    state.task = task
    state.scheduleVersion++
    state.absent = false
    if (state.loseResponse) throw new TypeError('Failed to fetch')
    return Response.json(task)
  })
  vi.stubGlobal('fetch', request)
  const client = createQueryClient()
  const router = createMemoryRouter(
    [
      { path: '/today/tasks/:taskId', element: <TaskPage /> },
      { path: '/today', element: <p>План дня</p> },
    ],
    { initialEntries: [`/today/tasks/${state.task.id}`] },
  )
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  const writes = () =>
    request.mock.calls.filter(([, init]) => init?.method && init.method !== 'GET')
  return { state, client, router, generation, writes, request }
}

async function savePlacement() {
  await userEvent.click(screen.getByRole('button', { name: 'Сохранить время' }))
  const confirmation = screen.queryByRole('dialog', { name: 'Перенести задачу' })
  if (!confirmation) return
  await userEvent.click(within(confirmation).getByRole('button', { name: 'Перенести' }))
  await waitFor(() => {
    if (confirmation.isConnected) expect(confirmation).toHaveAttribute('aria-busy', 'false')
  })
  if (confirmation.isConnected)
    await userEvent.click(within(confirmation).getByRole('button', { name: 'Отмена' }))
}

describe('task actions through the saved task panel', () => {
  it('keeps the chosen move time when confirmation is cancelled without sending a command', async () => {
    const { client, writes } = setup()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Перенести' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Перенести' }))
    fireEvent.change(screen.getByLabelText('Начало задачи'), {
      target: { value: '2026-11-12T11:15' },
    })
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить время' }))
    const confirmation = screen.getByRole('dialog', { name: 'Перенести задачу' })
    expect(confirmation).toHaveTextContent('11:15–12:45')
    expect(writes()).toHaveLength(0)
    await userEvent.click(within(confirmation).getByRole('button', { name: 'Отмена' }))
    expect(screen.getByLabelText('Начало задачи')).toHaveValue('2026-11-12T11:15')
    expect(writes()).toHaveLength(0)
    client.clear()
  })
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-11T04:42:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
    onlineManager.setOnline(true)
  })

  it('reports offline actions without queuing writes and recovers using reads after reconnecting', async () => {
    const { state, client, writes } = setup()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Закрепить' })).toBeEnabled())
    state.offline = true
    act(() => onlineManager.setOnline(false))
    await userEvent.click(screen.getByRole('button', { name: 'Выполнить' }))
    await screen.findByText(/Не удалось проверить результат/)
    expect(screen.getByRole('button', { name: 'Выполнить' })).toBeDisabled()
    expect(writes()).toHaveLength(1)
    state.offline = false
    await act(async () => onlineManager.setOnline(true))
    await userEvent.click(screen.getByRole('button', { name: 'Обновить данные задачи' }))
    await screen.findByText('Данные обновлены. Проверьте план перед повторным действием.')
    expect(screen.getByRole('button', { name: 'Выполнить' })).toBeEnabled()
    expect(writes()).toHaveLength(1)
    expect(state.task.status).toBe('scheduled')
    client.clear()
  })

  it('preserves the move draft and blocks writes when the recovery task read also fails', async () => {
    const { state, client, writes } = setup()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Перенести' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Перенести' }))
    fireEvent.change(screen.getByLabelText('Начало задачи'), {
      target: { value: '2026-11-11T15:00' },
    })
    state.offline = true
    await savePlacement()
    await screen.findByText(/Не удалось проверить результат/)
    expect(screen.getByLabelText('Начало задачи')).toHaveValue('2026-11-11T15:00')
    expect(screen.getByRole('button', { name: 'Сохранить время' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Удалить задачу' })).toBeDisabled()
    state.offline = false
    await userEvent.click(screen.getByRole('button', { name: 'Обновить данные задачи' }))
    await screen.findByText('Данные обновлены. Проверьте план перед повторным действием.')
    expect(screen.getByLabelText('Начало задачи')).toHaveValue('2026-11-11T15:00')
    expect(screen.getByRole('button', { name: 'Сохранить время' })).toBeEnabled()
    expect(writes()).toHaveLength(1)
    client.clear()
  })

  it('hides cached task actions when a refresh confirms that the task was deleted', async () => {
    const { client, request, generation, state, writes } = setup()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Перенести' })).toBeEnabled())
    const original = request.getMockImplementation()!
    request.mockImplementation(async (input, init) =>
      (!init?.method || init.method === 'GET') && String(input).endsWith(`/tasks/${state.task.id}`)
        ? failure('TASK_NOT_FOUND', 404)
        : original(input, init),
    )
    await act(async () =>
      client.invalidateQueries({ queryKey: taskKeys.detail(generation, state.task.id) }),
    )
    await screen.findByText('Задача удалена или недоступна.')
    expect(screen.queryByRole('button', { name: 'Выполнить' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Начало задачи')).not.toBeInTheDocument()
    expect(writes()).toHaveLength(0)
    client.clear()
  })

  it('shows readable server reasons and occupied times while preserving the move draft', async () => {
    const { state, client, writes } = setup({
      pinned: true,
      explanation:
        '10:00 +0500–11:30 +0500. Начало закреплено пользователем. Длительность: 90 мин.',
    })
    state.commandError = 'INTERVAL_OCCUPIED'
    state.commandMessage = 'Интервал занят задачей с 14:45 +0500 до 15:45 +0500.'
    await screen.findByText('Время закреплено вами.')
    await userEvent.click(screen.getByRole('button', { name: 'Перенести' }))
    fireEvent.change(screen.getByLabelText('Начало задачи'), {
      target: { value: '2026-11-11T14:45' },
    })
    await savePlacement()
    await screen.findByText(/Интервал занят задачей с 14:45 до 15:45\./)
    expect(screen.getByRole('dialog')).not.toHaveTextContent('+0500')
    expect(screen.getByRole('region', { name: 'Почему в это время' })).not.toHaveTextContent(
      'Длительность:',
    )
    expect(screen.getByLabelText('Начало задачи')).toHaveValue('2026-11-11T14:45')
    expect(writes()).toHaveLength(1)
    client.clear()
  })

  it('pins and unpins the confirmed interval using the latest returned task and plan versions', async () => {
    const { state, client, writes, generation } = setup()
    const otherTaskKey = taskKeys.detail(generation, fixture.tasks[4].id)
    client.setQueryData(otherTaskKey, fixture.tasks[4])
    await waitFor(() => expect(screen.getByRole('button', { name: 'Закрепить' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Закрепить' }))
    await screen.findByText('Время закреплено')
    expect(JSON.parse(String(writes()[0][1]?.body))).toEqual({
      planned_date: fixture.date,
      start_at: '2026-11-11T05:00:00Z',
      version: 3,
      schedule_versions: { [fixture.date]: 6 },
    })
    expect(client.getQueryState(otherTaskKey)?.isInvalidated).toBe(true)
    await userEvent.click(screen.getByRole('button', { name: 'Открепить' }))
    await screen.findByText('Время откреплено')
    const url = new URL(String(writes()[1][0]))
    expect(Object.fromEntries(url.searchParams)).toEqual({ version: '4', schedule_version: '7' })
    expect(writes()[1][1]?.body).toBeUndefined()
    expect(state.task.is_pinned).toBe(false)
    client.clear()
  })

  it('starts with server time, completes, reopens and skips without a separate replan command', async () => {
    const { state, client, writes } = setup()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Начать сейчас' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Начать сейчас' }))
    await screen.findByText('Задача начата', { selector: 'button' })
    expect(screen.getByRole('button', { name: 'Задача начата' })).toBeDisabled()
    expect(JSON.parse(String(writes()[0][1]?.body))).toEqual({
      version: 3,
      schedule_versions: { [fixture.date]: 6 },
    })
    expect(state.task.actual_start).toBe('2026-11-11T04:42:17Z')
    await userEvent.click(screen.getByRole('button', { name: 'Выполнить' }))
    await screen.findByText('Задача выполнена')
    await userEvent.click(screen.getByRole('button', { name: 'Вернуть в работу' }))
    await screen.findByText('Задача возвращена в работу')
    expect(state.task.status).toBe('scheduled')
    expect(state.task.actual_start).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Пропустить' }))
    await screen.findByText('Задача пропущена')
    expect(writes().map(([url]) => new URL(String(url)).pathname.split('/').at(-1))).toEqual([
      'start-now',
      'complete',
      'reopen',
      'skip',
    ])
    expect(
      writes()
        .slice(1)
        .map(([, init]) => JSON.parse(String(init?.body))),
    ).toEqual([{ version: 4 }, { version: 5 }, { version: 6 }])
    client.clear()
  })

  it('moves across days with versions for both days and converts the profile clock to UTC', async () => {
    const { client, writes } = setup()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Перенести' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Перенести' }))
    fireEvent.change(screen.getByLabelText('Начало задачи'), {
      target: { value: '2026-11-12T11:15' },
    })
    await savePlacement()
    await screen.findByText('План дня')
    expect(JSON.parse(String(writes()[0][1]?.body))).toEqual({
      planned_date: '2026-11-12',
      start_at: '2026-11-12T06:15:00.000Z',
      version: 3,
      schedule_versions: { '2026-11-11': 6, '2026-11-12': 4 },
    })
    expect(screen.queryByRole('form')).not.toBeInTheDocument()
    client.clear()
  })

  it('can pin an unplaced task when absence of a saved plan was confirmed by 404', async () => {
    const { client, writes } = setup({ absent: true, unplaced: true })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Закрепить' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Закрепить' }))
    fireEvent.change(screen.getByLabelText('Начало задачи'), {
      target: { value: '2026-11-11T11:15' },
    })
    await savePlacement()
    await screen.findByText('Время закреплено')
    expect(JSON.parse(String(writes()[0][1]?.body)).schedule_versions).toEqual({
      [fixture.date]: 0,
    })
    client.clear()
  })

  it.each(['TASK_VERSION_CONFLICT', 'SCHEDULE_VERSION_CONFLICT', 'INTERVAL_OCCUPIED'])(
    'preserves the selected time, refreshes versions and never replays %s',
    async (code) => {
      const { state, client, writes } = setup()
      state.commandError = code
      await waitFor(() => expect(screen.getByRole('button', { name: 'Перенести' })).toBeEnabled())
      await userEvent.click(screen.getByRole('button', { name: 'Перенести' }))
      fireEvent.change(screen.getByLabelText('Начало задачи'), {
        target: { value: '2026-11-11T11:15' },
      })
      await savePlacement()
      await screen.findByText(/Данные обновлены — проверьте их/)
      expect(screen.getByLabelText('Начало задачи')).toHaveValue('2026-11-11T11:15')
      expect(writes()).toHaveLength(1)
      state.commandError = ''
      await savePlacement()
      await screen.findByText('План дня')
      expect(JSON.parse(String(writes()[1][1]?.body))).toMatchObject({
        version: 8,
        schedule_versions: { [fixture.date]: 9 },
      })
      client.clear()
    },
  )

  it('reconciles a write with a lost response instead of blindly replaying it', async () => {
    const { state, client, writes } = setup()
    state.loseResponse = true
    await userEvent.click(await screen.findByRole('button', { name: 'Выполнить' }))
    await screen.findByText(/Данные обновлены — проверьте их/)
    expect(screen.getByRole('button', { name: 'Вернуть в работу' })).toBeEnabled()
    expect(state.task.status).toBe('done')
    expect(writes()).toHaveLength(1)
    client.clear()
  })

  it('blocks placement on a failed plan read instead of treating it as version zero', async () => {
    const { client, writes } = setup({ scheduleFailure: true })
    await screen.findByText('Расписание недоступно. Размещение не подтверждено.')
    expect(screen.getByRole('button', { name: 'Закрепить' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Начать сейчас' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Выполнить' })).toBeEnabled()
    expect(writes()).toHaveLength(0)
    client.clear()
  })

  it('requires successful reconciliation after an unknown result and a failed refresh', async () => {
    const { state, client, writes } = setup()
    state.scheduleFailure = true
    state.loseResponse = true
    await userEvent.click(await screen.findByRole('button', { name: 'Пропустить' }))
    await screen.findByText(/Не удалось проверить результат/)
    expect(screen.getByRole('button', { name: 'Вернуть в работу' })).toBeDisabled()
    state.scheduleFailure = false
    await userEvent.click(screen.getByRole('button', { name: 'Обновить данные задачи' }))
    await screen.findByText(/Данные обновлены\. Проверьте план/)
    expect(screen.getByRole('button', { name: 'Вернуть в работу' })).toBeEnabled()
    expect(writes()).toHaveLength(1)
    client.clear()
  })

  it('prevents duplicate actions and closing while pending; ignores a response after sign-out', async () => {
    const { state, client, router, writes, generation } = setup()
    let release!: () => void
    state.wait = new Promise<void>((resolve) => {
      release = resolve
    })
    const button = await screen.findByRole('button', { name: 'Выполнить' })
    fireEvent.click(button)
    fireEvent.click(button)
    await waitFor(() => expect(writes()).toHaveLength(1))
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(router.state.location.pathname).toContain('/tasks/')
    await act(async () => {
      useSessionStore.getState().signOut()
      release()
      await state.wait
    })
    expect(writes()[0][1]?.signal?.aborted).toBe(true)
    expect(client.getQueryData(taskKeys.detail(generation, state.task.id))).not.toMatchObject({
      status: 'done',
    })
    expect(client.getQueryData(scheduleKeys.day(generation, fixture.date))).not.toMatchObject({
      version: 7,
    })
    client.clear()
  })
})
