import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { onlineManager, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { createQueryClient } from '@/shared/api/queryClient'
import { scheduleKeys, taskKeys } from '@/shared/api/planningKeys'
import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { localDate } from '@/shared/lib/dateTime'
import { useSessionStore } from '@/stores/session'
import { mockMatchMedia } from '@/test/matchMedia'
import { NewTaskPage } from './NewTaskPage'
import { TodayPage } from './TodayPage'

vi.mock('./TodayTimeline', () => ({ TodayTimeline: () => null }))
vi.mock('./useTodaySchedule', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./useTodaySchedule')>()),
  useTodaySchedule: () => ({ version: undefined }),
}))
vi.mock('./TodayCriticalDays', () => ({ TodayCriticalDays: () => null }))
vi.mock('./TodayEnergyProfile', () => ({ TodayEnergyProfile: () => null }))

const timezone = 'Asia/Yekaterinburg'
const today = () => localDate(new Date(), timezone)
const taskResponse = (body: Record<string, unknown>) => ({
  ...DAILY_SCHEDULE_FIXTURES.normal.tasks[3],
  ...body,
  preferred_start: null,
  is_pinned: false,
  pinned_start: null,
  status: 'scheduled',
  version: 2,
})

function setup() {
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
  useSessionStore.setState({ timezone, isOnboarded: true })
  const generation = useSessionStore.getState().generation
  const client = createQueryClient()
  const router = createMemoryRouter(
    [
      {
        path: '/today',
        element: <TodayPage />,
        children: [{ path: 'new', element: <NewTaskPage /> }],
      },
      { path: '/other', element: <p>Другой экран</p> },
    ],
    { initialEntries: ['/today/new'] },
  )
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { client, router, generation }
}

async function fill() {
  await userEvent.type(
    screen.getByRole('textbox', { name: 'Название' }),
    'Подготовиться к экзамену',
  )
  await userEvent.click(screen.getByRole('radio', { name: 'Интеллектуальная' }))
  await userEvent.click(screen.getByRole('radio', { name: '30 мин' }))
}

function deferredResponse() {
  let resolve!: (value: Response) => void
  const promise = new Promise<Response>((done) => {
    resolve = done
  })
  const request = vi.fn<typeof fetch>(() => promise)
  vi.stubGlobal('fetch', request)
  return { request, resolve }
}

describe('task creation with the API', () => {
  afterEach(() => onlineManager.setOnline(true))

  it('reports an offline creation immediately and never sends a queued write after reconnection', async () => {
    const request = vi.fn<typeof fetch>(async () => {
      throw new TypeError('Failed to fetch')
    })
    vi.stubGlobal('fetch', request)
    const { client } = setup()
    await fill()
    act(() => onlineManager.setOnline(false))
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Нет связи с сервером')
    expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue(
      'Подготовиться к экзамену',
    )
    expect(screen.getByRole('button', { name: 'Добавить и распределить' })).toBeEnabled()
    expect(request).toHaveBeenCalledTimes(1)
    await act(async () => onlineManager.setOnline(true))
    expect(request).toHaveBeenCalledTimes(1)
    client.clear()
  })

  it('invalidates the displayed plan after an unconfirmed creation so closing the draft cannot leave a fresh stale list', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Lost response')
      }),
    )
    const { client, generation, router } = setup()
    const listKey = taskKeys.day(generation, today())
    const savedKey = scheduleKeys.day(generation, today())
    client.setQueryData(listKey, [])
    client.setQueryData(savedKey, { version: 1 })
    await fill()
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    await screen.findByRole('alert')
    expect(client.getQueryState(listKey)?.isInvalidated).toBe(true)
    expect(client.getQueryState(savedKey)?.isInvalidated).toBe(true)
    expect(router.state.location.pathname).toBe('/today/new')
    client.clear()
  })

  it('explains an automatic move of a physical task instead of implying placement today', async () => {
    const target = new Date(`${today()}T12:00:00Z`)
    target.setUTCDate(target.getUTCDate() + 3)
    const targetDate = target.toISOString().slice(0, 10)
    const request = vi.fn<typeof fetch>(async (_url, init) =>
      Response.json(taskResponse({ ...JSON.parse(String(init?.body)), planned_date: targetDate }), {
        status: 201,
      }),
    )
    vi.stubGlobal('fetch', request)
    const { router } = setup()
    await fill()
    await userEvent.click(screen.getByRole('radio', { name: 'Физическая' }))
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    expect(await screen.findByText(/Планировщик перенёс задачу с/)).toHaveTextContent(
      `Планировщик перенёс задачу с ${today().split('-').reverse().join('.')} на ${targetDate.split('-').reverse().join('.')}. На сегодняшнем таймлайне её не будет.`,
    )
    expect(JSON.parse(String(request.mock.calls[0][1]?.body)).type).toBe('physical')
    expect(router.state.location.pathname).toBe('/today')
    expect(screen.getByRole('button', { name: 'Открыть' })).toBeInTheDocument()
  })

  it.each([false, true])(
    'creates a task, updates account caches and confirms success (mobile=%s)',
    async (mobile) => {
      mockMatchMedia(mobile)
      const request = vi.fn<typeof fetch>(async (_url, init) =>
        Response.json(taskResponse(JSON.parse(String(init?.body))), { status: 201 }),
      )
      vi.stubGlobal('fetch', request)
      const { router, client, generation } = setup()
      const listKey = taskKeys.list(generation, { date: today() })
      const scheduleKey = scheduleKeys.day(generation, today())
      const otherAccount = scheduleKeys.day(generation + 1, today())
      client.setQueryData(listKey, { items: [], total: 0, limit: 50, offset: 0 })
      client.setQueryData(scheduleKey, { version: 1 })
      client.setQueryData(otherAccount, { version: 1 })
      await fill()
      await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
      expect(await screen.findByText('Задача добавлена')).toBeInTheDocument()
      expect(router.state.location.pathname).toBe('/today')
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(request).toHaveBeenCalledTimes(1)
      const [, init] = request.mock.calls[0]
      expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer test-token')
      expect(JSON.parse(String(init?.body))).toEqual({
        title: 'Подготовиться к экзамену',
        description: null,
        type: 'intellectual',
        priority: 'medium',
        duration_min: 30,
        planned_date: today(),
        deadline: null,
      })
      expect(
        client.getQueryData(
          taskKeys.detail(generation, DAILY_SCHEDULE_FIXTURES.normal.tasks[3].id),
        ),
      ).toMatchObject({ version: 2 })
      expect(client.getQueryState(listKey)?.isInvalidated).toBe(true)
      expect(client.getQueryState(scheduleKey)?.isInvalidated).toBe(true)
      expect(client.getQueryState(otherAccount)?.isInvalidated).toBe(false)
      await userEvent.click(screen.getByRole('button', { name: 'Закрыть уведомление' }))
      expect(screen.queryByText('Задача добавлена')).not.toBeInTheDocument()
      client.clear()
    },
  )

  it('prevents duplicate submission and closing while creation is in flight', async () => {
    const { request, resolve } = deferredResponse()
    const { router, client } = setup()
    await fill()
    const form = screen.getByRole('form', { name: 'Создание задачи' })
    fireEvent.submit(form)
    fireEvent.submit(form)
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('button', { name: 'Добавляем задачу…' })).toBeDisabled()
    expect(screen.getByRole('textbox', { name: 'Название' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Закрыть' })).toBeDisabled()
    await userEvent.keyboard('{Escape}')
    expect(router.state.location.pathname).toBe('/today/new')
    await act(async () => {
      resolve(
        Response.json(taskResponse(JSON.parse(String(request.mock.calls[0][1]?.body))), {
          status: 201,
        }),
      )
    })
    expect(await screen.findByText('Задача добавлена')).toBeInTheDocument()
    client.clear()
  })

  it('keeps the draft after field validation errors and focuses the invalid control', async () => {
    const request = vi.fn<typeof fetch>(async () =>
      Response.json(
        {
          error: {
            code: 'VALIDATION_ERROR',
            message: 'Ошибка проверки данных',
            details: {
              fields: [
                { field: 'body.title', code: 'INVALID', message: 'Уточните название задачи' },
              ],
            },
          },
        },
        { status: 422 },
      ),
    )
    vi.stubGlobal('fetch', request)
    const { router, client } = setup()
    await fill()
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    const input = screen.getByRole('textbox', { name: 'Название' })
    await waitFor(() => expect(input).toHaveAttribute('aria-invalid', 'true'))
    await waitFor(() => expect(input).toHaveFocus())
    expect(input).toHaveValue('Подготовиться к экзамену')
    expect(screen.getByRole('radio', { name: '30 мин' })).toBeChecked()
    expect(router.state.location.pathname).toBe('/today/new')
    await userEvent.type(input, '!')
    expect(input).not.toHaveAttribute('aria-invalid', 'true')
    expect(request).toHaveBeenCalledTimes(1)
    client.clear()
  })

  it('reveals a server error for a field inside Additional without losing form values', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        Response.json(
          {
            error: {
              code: 'VALIDATION_ERROR',
              message: 'Ошибка проверки данных',
              details: {
                fields: [
                  { field: 'body.planned_date', code: 'INVALID', message: 'Выберите другой день' },
                ],
              },
            },
          },
          { status: 422 },
        ),
      ),
    )
    const { client } = setup()
    await fill()
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    const day = await screen.findByLabelText('День задачи')
    await waitFor(() => expect(day).toHaveFocus())
    expect(day).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue(
      'Подготовиться к экзамену',
    )
    client.clear()
  })

  it.each(['network', '503', 'invalid-response'])(
    'preserves the draft and warns against a duplicate after %s',
    async (failure) => {
      const request = vi.fn<typeof fetch>(async () => {
        if (failure === 'network') throw new TypeError('Failed to fetch')
        return failure === '503'
          ? Response.json(
              { error: { code: 'PLANNER_UNAVAILABLE', message: 'Планировщик недоступен' } },
              { status: 503 },
            )
          : Response.json({ invalid: true }, { status: 201 })
      })
      vi.stubGlobal('fetch', request)
      const { router, client } = setup()
      await fill()
      await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Проверьте список задач перед повторной отправкой',
      )
      expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue(
        'Подготовиться к экзамену',
      )
      expect(router.state.location.pathname).toBe('/today/new')
      expect(request).toHaveBeenCalledTimes(1)
      client.clear()
    },
  )

  it.each([201, 401])(
    'does not apply or retry a late response under a new session (%s)',
    async (status) => {
      const { request, resolve } = deferredResponse()
      const { client, generation, router } = setup()
      await fill()
      await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
      await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
      act(() =>
        useSessionStore.setState({ generation: generation + 1, accessToken: 'other-account' }),
      )
      await act(async () => {
        resolve(
          Response.json(
            status === 201
              ? taskResponse(JSON.parse(String(request.mock.calls[0][1]?.body)))
              : { error: { code: 'TOKEN_EXPIRED', message: 'Сессия истекла' } },
            { status },
          ),
        )
      })
      expect(router.state.location.pathname).toBe('/today/new')
      expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue('')
      expect(
        client.getQueryData(
          taskKeys.detail(generation + 1, DAILY_SCHEDULE_FIXTURES.normal.tasks[3].id),
        ),
      ).toBeUndefined()
      expect(screen.queryByText('Задача добавлена')).not.toBeInTheDocument()
      expect(request).toHaveBeenCalledTimes(1)
      expect(request.mock.calls[0][1]?.signal?.aborted).toBe(true)
      client.clear()
    },
  )

  it('does not redirect after navigation away, but invalidates the same account data', async () => {
    const { request, resolve } = deferredResponse()
    const { client, generation, router } = setup()
    const key = scheduleKeys.day(generation, today())
    client.setQueryData(key, { version: 1 })
    await fill()
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
    await act(async () => {
      await router.navigate('/other')
    })
    await act(async () => {
      resolve(
        Response.json(taskResponse(JSON.parse(String(request.mock.calls[0][1]?.body))), {
          status: 201,
        }),
      )
    })
    await waitFor(() => expect(client.getQueryState(key)?.isInvalidated).toBe(true))
    expect(router.state.location.pathname).toBe('/other')
    client.clear()
  })

  it('makes unavailable options read-only rather than silently discarding choices', async () => {
    const { client } = setup()
    expect(screen.getByRole('radio', { name: 'Каждый день' })).toBeDisabled()
    expect(screen.getByRole('switch', { name: 'Закрепить время' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: /Ещё:/ }))
    expect(screen.getByRole('button', { name: /Желаемое время/ })).toBeEnabled()
    expect(screen.getByRole('combobox', { name: 'Напоминание' })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: 'Напоминание' })).toHaveValue('')
    expect(fetch).not.toHaveBeenCalled()
    client.clear()
  })

  it('sends a user-selected date and an absolute deadline in the profile timezone', async () => {
    const request = vi.fn<typeof fetch>(async (_url, init) =>
      init?.method === 'POST'
        ? Response.json(taskResponse(JSON.parse(String(init.body))), { status: 201 })
        : Response.json({ error: { code: 'SCHEDULE_NOT_FOUND', message: 'Нет расписания' } }, { status: 404 }),
    )
    vi.stubGlobal('fetch', request)
    const { client } = setup()
    await fill()
    await userEvent.click(screen.getByRole('button', { name: /Ещё:/ }))
    fireEvent.change(screen.getByLabelText('День задачи'), { target: { value: '2099-11-19' } })
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /Срок/ }), 'date')
    fireEvent.change(screen.getByLabelText('Дата дедлайна'), { target: { value: '2099-11-19' } })
    fireEvent.change(screen.getByLabelText('Время дедлайна'), { target: { value: '18:00' } })
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    expect(await screen.findByText('Задача добавлена')).toBeInTheDocument()
    expect(JSON.parse(String(request.mock.calls.find(([, init]) => init?.method === 'POST')![1]?.body))).toMatchObject({
      planned_date: '2099-11-19',
      deadline: '2099-11-19T13:00:00.000Z',
    })
    client.clear()
  })
})
