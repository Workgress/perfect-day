import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { onlineManager, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { createQueryClient } from '@/shared/api/queryClient'
import { scheduleKeys, taskKeys } from '@/shared/api/planningKeys'
import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import type { SavedSchedule } from '@/shared/model/schedule'
import { useSessionStore } from '@/stores/session'
import { TodayPage } from './TodayPage'

vi.mock('./TodayCriticalDays', () => ({ TodayCriticalDays: () => null }))
vi.mock('./TodayEnergyProfile', () => ({ TodayEnergyProfile: () => null }))

const fixture = DAILY_SCHEDULE_FIXTURES.normal
const failure = (code: string, status = 409) =>
  Response.json({ error: { code, message: code } }, { status })

function setup(options: { absent?: boolean; readFailure?: boolean } = {}) {
  useSessionStore.getState().signIn({
    accessToken: 'replan-token',
    user: {
      name: 'Анна',
      birthDate: '2003-09-20',
      chronotype: 'lark',
      workStart: '08:00',
      workEnd: '18:00',
    },
  })
  useSessionStore.setState({ timezone: fixture.timezone, isOnboarded: true })
  const generation = useSessionStore.getState().generation
  const pending = {
    ...fixture.tasks[5],
    id: '10000000-0000-4000-8000-000000000099',
    title: 'Новая задача для пересчёта',
    duration_min: 30,
    status: 'pending' as const,
  }
  const state = {
    tasks: [...structuredClone(fixture.tasks), pending],
    absent: options.absent ?? false,
    readFailure: options.readFailure ?? false,
    conflict: false,
    loseResponse: false,
    failAfterWrite: false,
    staleRead: false,
    offline: false,
    gate: undefined as Promise<void> | undefined,
    saved: {
      id: fixture.schedule!.id,
      planned_date: fixture.date,
      timezone: fixture.timezone,
      version: 6,
      algorithm_version: 'test',
      generated_at: '2026-11-11T04:00:00Z',
      slots: fixture.slots.map((slot) => ({ ...slot, reason_codes: [] })),
      unscheduled: [{ task_id: pending.id, reason_codes: ['NO_CONTIGUOUS_WINDOW'] }],
      warnings: [],
      moves: [],
      metrics: {
        requested_min: 450,
        planned_min: 420,
        capacity_min: 600,
        high_intensity_min: 180,
        critical_level: 0,
        load_factor: 1,
        moved_min: 0,
      },
    } as SavedSchedule,
  }
  const request = vi.fn<typeof fetch>(async (input) => {
    if (state.offline) throw new TypeError('Offline')
    const url = new URL(String(input))
    if (url.pathname.endsWith('/schedule/replan')) {
      await state.gate
      if (state.conflict) {
        state.saved.version = 9
        return failure('SCHEDULE_VERSION_CONFLICT')
      }
      state.saved.version++
      state.absent = false
      if (state.saved.unscheduled.length) {
        state.tasks = state.tasks.map((task) =>
          task.id === pending.id
            ? { ...task, status: 'scheduled', version: task.version + 1 }
            : task,
        )
        state.saved.slots.push({
          ...state.saved.slots[0],
          kind: 'task',
          id: '20000000-0000-4000-8000-000000000099',
          task_id: pending.id,
          start_at: '2026-11-11T12:00:00Z',
          end_at: '2026-11-11T12:30:00Z',
        })
        state.saved.unscheduled = []
      }
      state.readFailure = state.failAfterWrite
      if (state.loseResponse) throw new TypeError('Failed to fetch')
      return Response.json({
        schedule: state.saved,
        recommendations: [],
        placement_explanations: [],
        unscheduled_explanations: [],
        changes: [],
      })
    }
    if (state.readFailure) return failure('SERVICE_UNAVAILABLE', 503)
    if (url.pathname.endsWith('/schedule'))
      return state.absent
        ? failure('SCHEDULE_NOT_FOUND', 404)
        : Response.json({
            ...state.saved,
            version: state.saved.version - (state.staleRead ? 1 : 0),
          })
    if (url.pathname.endsWith('/tasks'))
      return Response.json({ items: state.tasks, total: state.tasks.length, limit: 100, offset: 0 })
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', request)
  const client = createQueryClient()
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/today']}>
        <TodayPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  const writes = () => request.mock.calls.filter(([, init]) => init?.method === 'POST')
  return { state, client, generation, writes, request, pending, view }
}

const button = () => screen.getByRole('button', { name: 'Перепланировать' })

describe('manual schedule replanning', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-11T04:42:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
    onlineManager.setOnline(true)
  })

  it('does not submit a replan until confirmed and allows cancellation', async () => {
    const { client, writes } = setup()
    await waitFor(() => expect(button()).toBeEnabled())
    await userEvent.click(button())
    expect(writes()).toHaveLength(0)
    expect(screen.getByRole('dialog', { name: 'Перепланировать день?' })).toHaveTextContent(
      'Новый план будет сохранён сразу.',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Отмена' }))
    expect(writes()).toHaveLength(0)
    expect(button()).toHaveFocus()
    client.clear()
  })

  it('fails an offline replan visibly and never replays its POST on reconnect', async () => {
    const { state, client, writes } = setup()
    await waitFor(() => expect(button()).toBeEnabled())
    state.offline = true
    act(() => onlineManager.setOnline(false))
    await userEvent.click(button())
    await userEvent.click(screen.getByRole('button', { name: 'Пересчитать план' }))
    await screen.findByText(
      'Не удалось проверить результат пересчёта. Обновите данные перед новым действием.',
    )
    expect(button()).toBeDisabled()
    state.offline = false
    await act(async () => onlineManager.setOnline(true))
    await userEvent.click(screen.getByRole('button', { name: 'Обновить данные плана' }))
    await screen.findByText('Данные обновлены. Проверьте план перед пересчётом.')
    expect(button()).toBeEnabled()
    expect(writes()).toHaveLength(1)
    expect(state.saved.version).toBe(6)
    client.clear()
  })

  it('does not announce success or unlock actions until reads reach the acknowledged replan version', async () => {
    const { state, writes, client } = setup()
    await waitFor(() => expect(button()).toBeEnabled())
    state.staleRead = true
    await userEvent.click(button())
    await userEvent.click(screen.getByRole('button', { name: 'Пересчитать план' }))
    await screen.findByText(/не удалось загрузить результат/)
    expect(button()).toBeDisabled()
    expect(screen.queryByText('План и нагрузка обновлены.')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Обновить данные плана' }))
    await screen.findByText(/Не удалось обновить план/)
    expect(button()).toBeDisabled()
    state.staleRead = false
    await userEvent.click(screen.getByRole('button', { name: 'Обновить данные плана' }))
    await screen.findByText('Данные обновлены. Проверьте план перед пересчётом.')
    expect(button()).toBeEnabled()
    expect(writes()).toHaveLength(1)
    client.clear()
  })

  it('sends the displayed version, refreshes load and preserves pinned and completed tasks', async () => {
    const { client, generation, state, writes, pending } = setup()
    const preserved = state.tasks.filter((task) => task.is_pinned || task.status === 'done')
    await waitFor(() => expect(button()).toBeEnabled())
    expect(screen.getByRole('img', { name: /Нагрузка: 420 из 600/ })).toBeInTheDocument()
    await userEvent.click(button())
    await userEvent.click(screen.getByRole('button', { name: 'Пересчитать план' }))
    await screen.findByText('План и нагрузка обновлены.')
    expect(JSON.parse(String(writes()[0][1]?.body))).toEqual({
      planned_date: fixture.date,
      schedule_version: 6,
      allow_date_change: false,
    })
    expect(screen.getByRole('img', { name: /Нагрузка: 450 из 600/ })).toBeInTheDocument()
    expect(client.getQueryData(scheduleKeys.day(generation, fixture.date))).toEqual(state.saved)
    for (const task of preserved)
      expect(client.getQueryData(taskKeys.detail(generation, task.id))).toEqual(task)
    expect(client.getQueryData(taskKeys.detail(generation, pending.id))).toMatchObject({
      status: 'scheduled',
    })
    expect(writes()).toHaveLength(1)
    client.clear()
  })

  it('refreshes on conflict without retrying and uses the new version on a manual retry', async () => {
    const { state, writes, client } = setup()
    state.conflict = true
    await waitFor(() => expect(button()).toBeEnabled())
    await userEvent.click(button())
    await userEvent.click(screen.getByRole('button', { name: 'Пересчитать план' }))
    await screen.findByText(/Расписание изменилось. Данные обновлены/)
    expect(writes()).toHaveLength(1)
    state.conflict = false
    await userEvent.click(button())
    await userEvent.click(screen.getByRole('button', { name: 'Пересчитать план' }))
    await screen.findByText('План и нагрузка обновлены.')
    expect(JSON.parse(String(writes()[1][1]?.body)).schedule_version).toBe(9)
    client.clear()
  })

  it('reads back a saved result after response loss without sending another command', async () => {
    const { state, writes, client } = setup()
    state.loseResponse = true
    await waitFor(() => expect(button()).toBeEnabled())
    await userEvent.click(button())
    await userEvent.click(screen.getByRole('button', { name: 'Пересчитать план' }))
    await screen.findByText(/Загружен актуальный план/)
    expect(screen.getByRole('img', { name: /Нагрузка: 450 из 600/ })).toBeInTheDocument()
    expect(writes()).toHaveLength(1)
    expect(button()).toBeEnabled()
    client.clear()
  })

  it('blocks another command until failed result reads are recovered with GET requests', async () => {
    const { state, writes, client, view } = setup()
    state.failAfterWrite = true
    await waitFor(() => expect(button()).toBeEnabled())
    await userEvent.click(button())
    await userEvent.click(screen.getByRole('button', { name: 'Пересчитать план' }))
    await screen.findByRole('alert')
    expect(button()).toBeDisabled()
    view.rerender(
      <QueryClientProvider client={client}>
        <MemoryRouter key="reopened" initialEntries={['/today']}>
          <TodayPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('не удалось загрузить результат')
    expect(button()).toBeDisabled()
    state.readFailure = false
    await userEvent.click(screen.getByRole('button', { name: 'Обновить данные плана' }))
    await screen.findByText('Данные обновлены. Проверьте план перед пересчётом.')
    expect(writes()).toHaveLength(1)
    expect(button()).toBeEnabled()
    client.clear()
  })

  it('uses version zero only for a confirmed absent schedule', async () => {
    const { writes, client } = setup({ absent: true })
    await waitFor(() => expect(button()).toBeEnabled())
    await userEvent.click(button())
    await userEvent.click(screen.getByRole('button', { name: 'Пересчитать план' }))
    await screen.findByText('План и нагрузка обновлены.')
    expect(JSON.parse(String(writes()[0][1]?.body)).schedule_version).toBe(0)
    client.clear()
  })

  it('does not allow replanning when initial data cannot be read', async () => {
    const { client, writes } = setup({ readFailure: true })
    await screen.findByRole('alert')
    expect(button()).toBeDisabled()
    expect(writes()).toHaveLength(0)
    client.clear()
  })

  it('blocks duplicate commands and task actions while the request is pending', async () => {
    const { client, state, writes } = setup()
    let release!: () => void
    state.gate = new Promise<void>((resolve) => {
      release = resolve
    })
    await waitFor(() => expect(button()).toBeEnabled())
    const trigger = button()
    fireEvent.click(trigger)
    const confirm = screen.getByRole('button', { name: 'Пересчитать план' })
    fireEvent.click(confirm)
    fireEvent.click(confirm)
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(
      screen
        .getAllByRole('button', { name: 'Обновляем план…' })
        .every((item) => item.hasAttribute('disabled')),
    ).toBe(true)
    expect(screen.getByRole('button', { name: 'Начать' })).toBeDisabled()
    await act(async () => release())
    await screen.findByText('План и нагрузка обновлены.')
    client.clear()
  })

  it('aborts requests and discards results after an account change', async () => {
    const { client, state, writes, generation } = setup()
    let release!: () => void
    state.gate = new Promise<void>((resolve) => {
      release = resolve
    })
    await waitFor(() => expect(button()).toBeEnabled())
    fireEvent.click(button())
    fireEvent.click(screen.getByRole('button', { name: 'Пересчитать план' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    const signal = writes()[0][1]?.signal
    act(() => useSessionStore.getState().signIn({ accessToken: 'another-account' }))
    expect(signal?.aborted).toBe(true)
    await act(async () => release())
    await waitFor(() => expect(client.isMutating()).toBe(0))
    expect(screen.queryByText('План и нагрузка обновлены.')).not.toBeInTheDocument()
    expect(
      client.getQueryData<SavedSchedule>(scheduleKeys.day(generation, fixture.date))?.version,
    ).toBe(6)
    client.clear()
  })
})
