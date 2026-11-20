import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { createQueryClient } from '@/shared/api/queryClient'
import { createBiorhythmDemoPoints } from '@/shared/fixtures/biorhythms'
import { useSessionStore } from '@/stores/session'
import { BiorhythmsRoute } from '@/pages/biorhythms/BiorhythmsPage'
import { TodayPage } from './TodayPage'
import { criticalDayCopy } from './todayHeaderModel'

vi.mock('./TodayTimeline', () => ({ TodayTimeline: () => <p>План доступен</p> }))

const days = ['2026-11-21', '2026-11-22']
function criticalResponse(url: URL, dates = days, timezone = 'Asia/Yekaterinburg') {
  return Response.json({
    start: url.searchParams.get('from'),
    end: url.searchParams.get('to'),
    algorithm_version: '1.0.0',
    timezone,
    days: dates.map((date) => ({
      date,
      level: 1,
      kind: 'single',
      crossings: [{ cycle: 'physical', at: `${date}T10:00:00+05:00` }],
    })),
  })
}

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
  useSessionStore.setState({ timezone: 'Asia/Yekaterinburg', isOnboarded: true })
  const client = createQueryClient()
  const router = createMemoryRouter(
    [
      { path: '/today', element: <TodayPage /> },
      { path: '/biorhythms', element: <BiorhythmsRoute /> },
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

describe('today greeting and critical days', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-20T04:42:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('uses the personal API dates and shows the Figma banner after the greeting and date', async () => {
    const request = vi.fn<typeof fetch>(async (input) => criticalResponse(new URL(String(input))))
    vi.stubGlobal('fetch', request)
    const { client } = setup()
    expect(screen.getByText('Доброе утро, Анна')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Пятница, 20 ноября')
    const banner = await screen.findByRole('region', {
      name: 'Впереди критические дни: сб 21 и вс 22',
    })
    expect(banner).toHaveTextContent(
      'Отметки у нуля по модели — 21 и 22 ноября. Сверьтесь с самочувствием перед планированием.',
    )
    expect(new URL(String(request.mock.calls[0][0])).searchParams.toString()).toBe(
      'from=2026-11-20&to=2026-11-26',
    )
    expect(new Headers(request.mock.calls[0][1]?.headers).get('Authorization')).toBe(
      'Bearer test-token',
    )
    expect(request).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('img', { name: /график/i })).not.toBeInTheDocument()
    client.clear()
  })

  it('hides the warning when the API returns no critical days', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input) => criticalResponse(new URL(String(input)), [])),
    )
    const { client } = setup()
    await waitFor(() =>
      expect(screen.queryByText('Проверяем ближайшие критические дни…')).not.toBeInTheDocument(),
    )
    expect(screen.queryByRole('button', { name: 'Открыть неделю' })).not.toBeInTheDocument()
    expect(screen.getByText('План доступен')).toBeInTheDocument()
    client.clear()
  })

  it('shows today honestly when a critical day is already here', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input) => criticalResponse(new URL(String(input)), ['2026-11-20'])),
    )
    const { client } = setup()
    expect(
      await screen.findByRole('region', { name: 'Сегодня критический день' }),
    ).toHaveTextContent('Отметка у нуля по модели — 20 ноября.')
    client.clear()
  })

  it('shows an independent retry on failure without blocking the plan', async () => {
    let failed = true
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input) =>
        failed
          ? Response.json({ error: { code: 'INTERNAL_ERROR', message: 'Ошибка' } }, { status: 500 })
          : criticalResponse(new URL(String(input))),
      ),
    )
    const { client } = setup()
    await screen.findByText('Не удалось проверить ближайшие критические дни.')
    expect(screen.getByText('План доступен')).toBeInTheDocument()
    expect(screen.queryByText(/Впереди критические дни/)).not.toBeInTheDocument()
    failed = false
    await userEvent.click(screen.getByRole('button', { name: 'Повторить проверку' }))
    await screen.findByRole('button', { name: 'Открыть неделю' })
    client.clear()
  })

  it('opens the week containing the nearest critical date rather than the default month', async () => {
    const request = vi.fn<typeof fetch>(async (input) => {
      const url = new URL(String(input))
      if (url.pathname.endsWith('/critical-days')) return criticalResponse(url)
      const forecast = url.pathname.endsWith('/forecast')
      const start = forecast ? '2026-11-20' : url.searchParams.get('from')!
      const end = forecast ? '2026-11-26' : url.searchParams.get('to')!
      return Response.json({
        start,
        end,
        period: forecast ? 'week' : null,
        step: 'day',
        timezone: 'Asia/Yekaterinburg',
        algorithm_version: '1.0.0',
        points: createBiorhythmDemoPoints(start, end),
      })
    })
    vi.stubGlobal('fetch', request)
    const { client, router } = setup()
    await userEvent.click(await screen.findByRole('button', { name: 'Открыть неделю' }))
    await screen.findByRole('heading', { name: 'Биоритмы' })
    expect(router.state.location.search).toBe('?period=week&date=2026-11-21')
    expect(screen.getByRole('radio', { name: 'Неделя' })).toHaveAttribute('aria-checked', 'true')
    await waitFor(() =>
      expect(
        request.mock.calls.some(([url]) => {
          const params = new URL(String(url)).searchParams
          return params.get('from') === '2026-11-16' && params.get('to') === '2026-11-22'
        }),
      ).toBe(true),
    )
    client.clear()
  })

  it('updates the greeting, date and API range at midnight in the profile timezone', async () => {
    vi.setSystemTime(new Date('2026-11-20T18:59:00Z'))
    const request = vi.fn<typeof fetch>(async (input) =>
      criticalResponse(new URL(String(input)), []),
    )
    vi.stubGlobal('fetch', request)
    const { client } = setup()
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
    expect(screen.getByText('Добрый вечер, Анна')).toBeInTheDocument()
    vi.setSystemTime(new Date('2026-11-20T19:01:00Z'))
    fireEvent(window, new Event('focus'))
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Суббота, 21 ноября')
    expect(screen.getByText('Доброй ночи, Анна')).toBeInTheDocument()
    await waitFor(() =>
      expect(
        request.mock.calls.some(
          ([url]) => new URL(String(url)).searchParams.get('from') === '2026-11-21',
        ),
      ).toBe(true),
    )
    client.clear()
  })

  it('rejects a response for another timezone', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input) => criticalResponse(new URL(String(input)), days, 'UTC')),
    )
    const { client } = setup()
    await screen.findByText('Не удалось проверить ближайшие критические дни.')
    expect(screen.queryByRole('button', { name: 'Открыть неделю' })).not.toBeInTheDocument()
    client.clear()
  })

  it('aborts the old account request and never renders its critical dates after sign-out', async () => {
    let resolve!: (response: Response) => void
    const pending = new Promise<Response>((done) => {
      resolve = done
    })
    const request = vi.fn<typeof fetch>(() => pending)
    vi.stubGlobal('fetch', request)
    const { client } = setup()
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
    await act(async () => {
      useSessionStore.getState().signOut()
      resolve(criticalResponse(new URL(String(request.mock.calls[0][0]))))
      await pending
    })
    expect(request.mock.calls[0][1]?.signal?.aborted).toBe(true)
    expect(screen.queryByRole('button', { name: 'Открыть неделю' })).not.toBeInTheDocument()
    client.clear()
  })

  it('formats dates spanning months without assigning them to the wrong month', () => {
    expect(criticalDayCopy(['2026-11-30', '2026-12-02'], '2026-11-28').description).toContain(
      '30 ноября и 2 декабря',
    )
  })
})
