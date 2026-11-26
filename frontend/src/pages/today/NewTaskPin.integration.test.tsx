import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { createQueryClient } from '@/shared/api/queryClient'
import { taskKeys } from '@/shared/api/planningKeys'
import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { savedFixture } from '@/test/planningDetails'
import { mockMatchMedia } from '@/test/matchMedia'
import { useSessionStore } from '@/stores/session'
import type { Task } from '@/shared/model/task'
import type { SavedSchedule } from '@/shared/model/schedule'
import { NewTaskPage } from './NewTaskPage'

const fixture = DAILY_SCHEDULE_FIXTURES.normal
const start = '2026-11-11T06:00:00.000Z'
const fail = (code: string, status = 409) =>
  Response.json({ error: { code, message: code } }, { status })

function setup({ mobile = false, autoDate = fixture.date, missingTarget = false } = {}) {
  mockMatchMedia(!mobile)
  useSessionStore.getState().signIn({
    accessToken: 'pin-create-token',
    user: {
      name: 'Анна',
      birthDate: '2000-01-01',
      chronotype: 'lark',
      workStart: '08:00',
      workEnd: '18:00',
    },
  })
  useSessionStore.setState({ timezone: fixture.timezone, isOnboarded: true })
  const generation = useSessionStore.getState().generation
  const plans = new Map<string, SavedSchedule>()
  for (const date of new Set([autoDate, fixture.date])) {
    if (missingTarget && date === fixture.date) continue
    plans.set(date, { ...savedFixture(fixture), planned_date: date, version: 6, slots: [] })
  }
  const state = {
    task: null as Task | null,
    pinError: '',
    planFailure: false,
    losePinResponse: false,
    failReadback: false,
    pinCommitted: false,
    gate: undefined as Promise<void> | undefined,
  }
  const request = vi.fn<typeof fetch>(async (input, init) => {
    const url = new URL(String(input))
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : {}
    if (url.pathname.endsWith('/tasks') && method === 'POST') {
      state.task = {
        ...fixture.tasks[2],
        ...body,
        planned_date: autoDate,
        version: 2,
        status: 'scheduled',
        is_pinned: false,
        pinned_start: null,
        preferred_start: null,
      }
      return Response.json(state.task, { status: 201 })
    }
    if (url.pathname.endsWith('/schedule')) {
      if (state.planFailure || (state.pinCommitted && state.failReadback))
        return fail('SERVICE_UNAVAILABLE', 503)
      const saved = plans.get(url.searchParams.get('date')!)
      return saved ? Response.json(saved) : fail('SCHEDULE_NOT_FOUND', 404)
    }
    if (url.pathname.endsWith('/pin')) {
      await state.gate
      if (state.pinError) {
        state.task!.version = 8
        plans.get(autoDate)!.version = 9
        return fail(state.pinError)
      }
      state.task = {
        ...state.task!,
        planned_date: body.planned_date,
        is_pinned: true,
        pinned_start: body.start_at,
        version: state.task!.version + 1,
      }
      const saved = plans.get(body.planned_date) ?? { ...savedFixture(fixture), slots: [] }
      plans.set(body.planned_date, {
        ...saved,
        version: saved.version + 1,
        slots: [
          {
            ...fixture.slots[0],
            kind: 'task',
            task_id: state.task.id,
            is_pinned: true,
            reason_codes: [],
            start_at: body.start_at,
            end_at: new Date(
              Date.parse(body.start_at) + state.task.duration_min * 60_000,
            ).toISOString(),
          },
        ],
      })
      state.pinCommitted = true
      if (state.losePinResponse) throw new TypeError('Lost pin response')
      return Response.json(state.task)
    }
    if (method === 'GET' && state.task && url.pathname.endsWith('/' + state.task.id)) {
      if (state.pinCommitted && state.failReadback) throw new TypeError('Offline')
      return Response.json(state.task)
    }
    throw new Error(`Unexpected request: ${method} ${url.pathname}`)
  })
  vi.stubGlobal('fetch', request)
  const client = createQueryClient()
  const router = createMemoryRouter(
    [
      { path: '/today/new', element: <NewTaskPage /> },
      { path: '/today', element: <p>План дня</p> },
      { path: '/today/tasks/:id', element: <p>Открыта сохранённая задача</p> },
    ],
    { initialEntries: ['/today/new'] },
  )
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  const writes = () => request.mock.calls.filter(([, init]) => init?.method === 'POST')
  return { state, plans, client, router, generation, writes, request }
}

async function fill(time = '11:00') {
  await userEvent.type(
    screen.getByRole('textbox', { name: 'Название' }),
    'Задача в выбранное время',
  )
  await userEvent.click(screen.getByRole('radio', { name: 'Рутина' }))
  await userEvent.click(screen.getByRole('radio', { name: '30 мин' }))
  await userEvent.click(screen.getByRole('button', { name: /Ещё:|Дополнительно/ }))
  await userEvent.click(screen.getByRole('button', { name: /Желаемое время/ }))
  await userEvent.click(screen.getByRole('button', { name: /Указать время вручную/ }))
  fireEvent.change(screen.getByLabelText('Время начала'), { target: { value: time } })
  await userEvent.click(screen.getByRole('button', { name: `Выбрать ${time}` }))
}

describe('create a task with a pinned start', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-11T04:42:00Z'))
  })
  afterEach(() => vi.useRealTimers())

  it('cancels the mobile time sheet without closing the task creation dialog', async () => {
    const { client, router } = setup({ mobile: true })
    await userEvent.click(screen.getByRole('button', { name: /Дополнительно/ }))
    await userEvent.click(screen.getByRole('button', { name: /Желаемое время/ }))
    fireEvent(
      screen.getByRole('dialog', { name: 'Когда поставить' }),
      new Event('cancel', { cancelable: true }),
    )
    expect(screen.queryByRole('dialog', { name: 'Когда поставить' })).not.toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Новая задача' })).toBeVisible()
    expect(router.state.location.pathname).toBe('/today/new')
    client.clear()
  })

  it('selects a free interval on another day and creates then pins it after confirmation', async () => {
    const { client, writes } = setup()
    await userEvent.type(screen.getByRole('textbox', { name: 'Название' }), 'Свободное окно')
    await userEvent.click(screen.getByRole('radio', { name: 'Рутина' }))
    await userEvent.click(screen.getByRole('radio', { name: '1 ч' }))
    await userEvent.click(screen.getByRole('button', { name: /Ещё:/ }))
    await userEvent.click(screen.getByRole('button', { name: /Желаемое время/ }))
    const tomorrow = await screen.findByRole('radio', { name: /Завтра · 08:00–09:00/ })
    await userEvent.click(tomorrow)
    expect(writes()).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: 'Выбрать 08:00' }))
    expect(screen.getByRole('switch', { name: 'Закрепить время' })).toBeChecked()
    expect(screen.getByLabelText('Дата начала')).toHaveValue('2026-11-12')
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и закрепить' }))
    await screen.findByText('План дня')
    expect(writes()).toHaveLength(2)
    expect(JSON.parse(String(writes()[0][1]?.body)).planned_date).toBe('2026-11-12')
    expect(JSON.parse(String(writes()[1][1]?.body))).toMatchObject({
      planned_date: '2026-11-12',
      start_at: '2026-11-12T03:00:00.000Z',
    })
    client.clear()
  })

  it('keeps manual entry available when all schedule reads fail', async () => {
    const { client, state, writes } = setup()
    state.planFailure = true
    await fill()
    expect(screen.getByLabelText('Время начала')).toHaveValue('11:00')
    expect(screen.getByRole('switch', { name: 'Закрепить время' })).toBeChecked()
    expect(writes()).toHaveLength(0)
    client.clear()
  })

  it.each([false, true])(
    'chooses time within additional options and pins only after confirmation (mobile=%s)',
    async (mobile) => {
      const { client, writes } = setup({ mobile })
      expect(screen.queryByRole('button', { name: /Желаемое время/ })).not.toBeInTheDocument()
      const disclosure = screen.getByRole('button', { name: /Ещё:|Дополнительно/ })
      await userEvent.click(disclosure)
      const desired = screen.getByRole('button', { name: /Желаемое время/ })
      expect(document.getElementById(disclosure.getAttribute('aria-controls')!)).toContainElement(
        desired,
      )
      const pin = screen.getByRole('switch', { name: 'Закрепить время' })
      expect(desired).toHaveTextContent('Не важно — подберём сами')
      await userEvent.click(desired)
      expect(pin).not.toBeChecked()
      await userEvent.click(screen.getByRole('button', { name: /Указать время вручную/ }))
      fireEvent.change(screen.getByLabelText('Время начала'), { target: { value: '11:00' } })
      await userEvent.click(screen.getByRole('button', { name: 'Выбрать 11:00' }))
      expect(pin).toBeChecked()
      expect(screen.getByLabelText('Время начала')).toHaveValue('11:00')
      await userEvent.click(screen.getByRole('button', { name: 'Подобрать время автоматически' }))
      expect(pin).not.toBeChecked()
      expect(screen.queryByLabelText('Время начала')).not.toBeInTheDocument()
      await userEvent.click(pin)
      expect(screen.getByRole('heading', { name: 'Когда поставить' })).toBeVisible()
      expect(pin).not.toBeChecked()
      if (mobile) await userEvent.keyboard('{Escape}')
      else await userEvent.click(screen.getByRole('button', { name: 'Закрыть выбор времени' }))
      expect(screen.getByRole('heading', { name: 'Новая задача' })).toBeVisible()
      await userEvent.click(disclosure)
      expect(desired).not.toBeVisible()
      expect(writes()).toHaveLength(0)
      client.clear()
    },
  )

  it.each([false, true])(
    'creates then pins in profile timezone without sending placement fields to CRUD (mobile=%s)',
    async (mobile) => {
      const { client, router, writes, generation, state } = setup({ mobile })
      await fill()
      await userEvent.click(screen.getByRole('button', { name: 'Добавить и закрепить' }))
      await screen.findByText('План дня')
      expect(writes()).toHaveLength(2)
      expect(JSON.parse(String(writes()[0][1]?.body))).toEqual({
        title: 'Задача в выбранное время',
        type: 'routine',
        priority: 'medium',
        duration_min: 30,
        planned_date: fixture.date,
        description: null,
        deadline: null,
      })
      expect(JSON.parse(String(writes()[1][1]?.body))).toEqual({
        planned_date: fixture.date,
        start_at: start,
        version: 2,
        schedule_versions: { [fixture.date]: 6 },
      })
      expect(client.getQueryData(taskKeys.detail(generation, state.task!.id))).toMatchObject({
        is_pinned: true,
        pinned_start: start,
      })
      expect(router.state.location.state.taskCreated.task.is_pinned).toBe(true)
      client.clear()
    },
  )

  it('uses both actual and selected date versions when creation moved the task automatically', async () => {
    const { client, writes } = setup({ autoDate: '2026-11-12', missingTarget: true })
    await fill()
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и закрепить' }))
    await screen.findByText('План дня')
    expect(JSON.parse(String(writes()[1][1]?.body)).schedule_versions).toEqual({
      '2026-11-12': 6,
      [fixture.date]: 0,
    })
    client.clear()
  })

  it('rejects a past start before creating a task', async () => {
    const { client, writes } = setup()
    await fill('09:00')
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и закрепить' }))
    await screen.findByText('Выберите время в будущем.')
    expect(writes()).toHaveLength(0)
    client.clear()
  })

  it('turns pinning off and returns to automatic placement without a pin command', async () => {
    const { client, writes } = setup()
    await fill()
    await userEvent.click(screen.getByRole('switch', { name: 'Закрепить время' }))
    expect(screen.queryByLabelText('Время начала')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    await screen.findByText('План дня')
    expect(writes()).toHaveLength(1)
    client.clear()
  })

  it.each(['INTERVAL_OCCUPIED', 'SCHEDULE_VERSION_CONFLICT'])(
    'retains the created task and retries only pinning with fresh versions after %s',
    async (code) => {
      const { state, client, writes } = setup()
      state.pinError = code
      await fill()
      await userEvent.click(screen.getByRole('button', { name: 'Добавить и закрепить' }))
      await screen.findByRole('dialog', { name: 'Закрепление времени' })
      expect(screen.getByRole('alert')).toHaveTextContent('Задача создана')
      expect(screen.getByLabelText('Начало задачи')).toHaveValue('2026-11-11T11:00')
      state.pinError = ''
      fireEvent.change(screen.getByLabelText('Начало задачи'), {
        target: { value: '2026-11-11T12:00' },
      })
      await userEvent.click(screen.getByRole('button', { name: 'Закрепить время' }))
      await screen.findByText('План дня')
      expect(writes()).toHaveLength(3)
      expect(JSON.parse(String(writes()[2][1]?.body))).toMatchObject({
        version: 8,
        start_at: '2026-11-11T07:00:00.000Z',
        schedule_versions: { [fixture.date]: 9 },
      })
      expect(writes().filter(([url]) => String(url).endsWith('/tasks'))).toHaveLength(1)
      client.clear()
    },
  )

  it('does not treat failed plan reads as version zero and can retry without creating again', async () => {
    const { state, client, writes } = setup()
    state.planFailure = true
    await fill()
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и закрепить' }))
    await screen.findByRole('dialog', { name: 'Закрепление времени' })
    expect(writes()).toHaveLength(1)
    state.planFailure = false
    await userEvent.click(screen.getByRole('button', { name: 'Закрепить время' }))
    await screen.findByText('План дня')
    expect(writes()).toHaveLength(2)
    client.clear()
  })

  it.each([false, true])(
    'confirms a committed pin after response loss without replaying writes (failed readback=%s)',
    async (failReadback) => {
      const { state, client, writes } = setup()
      state.losePinResponse = true
      state.failReadback = failReadback
      await fill()
      await userEvent.click(screen.getByRole('button', { name: 'Добавить и закрепить' }))
      if (failReadback) {
        await screen.findByRole('dialog', { name: 'Закрепление времени' })
        state.failReadback = false
        await userEvent.click(screen.getByRole('button', { name: 'Закрепить время' }))
      }
      await screen.findByText('План дня')
      expect(writes()).toHaveLength(2)
      client.clear()
    },
  )

  it('aborts the second request and ignores its result after an account change', async () => {
    const { state, client, writes, router, generation } = setup()
    let release!: () => void
    state.gate = new Promise((resolve) => {
      release = resolve
    })
    await fill()
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и закрепить' }))
    await waitFor(() => expect(writes()).toHaveLength(2))
    const signal = writes()[1][1]?.signal
    await act(async () => {
      useSessionStore.getState().signOut()
      release()
    })
    await waitFor(() => expect(client.isMutating()).toBe(0))
    expect(signal?.aborted).toBe(true)
    expect(router.state.location.pathname).toBe('/today/new')
    expect(client.getQueryData(taskKeys.detail(generation, fixture.tasks[2].id))).toBeUndefined()
    client.clear()
  })

  it('prevents duplicate submissions and closing while the pin request is pending', async () => {
    const { state, client, writes, router } = setup()
    let release!: () => void
    state.gate = new Promise((resolve) => {
      release = resolve
    })
    await fill()
    const form = screen.getByRole('form', { name: 'Создание задачи' })
    fireEvent.submit(form)
    fireEvent.submit(form)
    await waitFor(() => expect(writes()).toHaveLength(2))
    expect(screen.getByRole('button', { name: 'Добавляем и закрепляем…' })).toBeDisabled()
    await userEvent.keyboard('{Escape}')
    expect(router.state.location.pathname).toBe('/today/new')
    await act(async () => release())
    await screen.findByText('План дня')
    expect(writes()).toHaveLength(2)
    client.clear()
  })

  it.each(['open', 'close'])(
    'allows leaving a failed pin without losing or recreating the saved task (%s)',
    async (action) => {
      const { state, client, writes, router } = setup()
      state.pinError = 'INTERVAL_OCCUPIED'
      await fill()
      await userEvent.click(screen.getByRole('button', { name: 'Добавить и закрепить' }))
      await screen.findByRole('dialog', { name: 'Закрепление времени' })
      if (action === 'open') {
        await userEvent.click(screen.getByRole('button', { name: 'Открыть задачу' }))
        await screen.findByText('Открыта сохранённая задача')
        expect(router.state.location.pathname).toBe(`/today/tasks/${state.task!.id}`)
      } else {
        await userEvent.keyboard('{Escape}')
        await screen.findByText('План дня')
        expect(router.state.location.state.taskNotice.message).toContain('Проверьте её время')
        expect(router.state.location.state.taskCreated).toBeUndefined()
      }
      expect(writes()).toHaveLength(2)
      client.clear()
    },
  )
})
