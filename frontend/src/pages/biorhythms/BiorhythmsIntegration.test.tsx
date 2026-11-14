import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createBiorhythmDemoPoints } from '@/shared/fixtures/biorhythms'
import { useSessionStore } from '@/stores/session'
import { BiorhythmsPage } from './BiorhythmsPage'

function response(start: string, end: string, period: 'week' | null = null) {
  return Response.json({
    start,
    end,
    period,
    step: 'day',
    timezone: 'Asia/Yekaterinburg',
    algorithm_version: '1.0.0',
    points: createBiorhythmDemoPoints(start, end),
  })
}

function serve(input: RequestInfo | URL) {
  const url = new URL(String(input))
  if (url.pathname.endsWith('/forecast')) return response('2026-11-11', '2026-11-17', 'week')
  return response(url.searchParams.get('from')!, url.searchParams.get('to')!)
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  render(
    <QueryClientProvider client={client}>
      <BiorhythmsPage />
    </QueryClientProvider>,
  )
  return client
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-11-11T10:00:00Z'))
  useSessionStore.setState({
    status: 'authenticated',
    accessToken: 'test-token',
    ownerId: 'owner-1',
    timezone: 'Asia/Yekaterinburg',
    user: { id: 'owner-1', name: 'Test', birthDate: '2000-01-01', chronotype: null },
  })
})

afterEach(() => vi.useRealTimers())

describe('personal biorhythm integration', () => {
  it.each([2, 3] as const)(
    'shows a level %i critical day before today in the selected period',
    async (level) => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (input: RequestInfo | URL) => {
          const result = await serve(input).json()
          for (const point of result.points) {
            point.critical =
              point.date === '2026-11-02'
                ? {
                    level,
                    kind: level === 3 ? 'triple' : 'double',
                    crossings: ['physical', 'emotional', 'intellectual']
                      .slice(0, level)
                      .map((cycle) => ({ cycle, at: point.at })),
                  }
                : { level: 0, kind: 'none', crossings: [] }
          }
          return Response.json(result)
        }),
      )
      mount()
      const banner = await screen.findByRole('region', {
        name: level === 3 ? 'Тройной критический день' : 'Двойной критический день',
      })
      expect(banner).toHaveTextContent('2 ноября')
      await userEvent.click(within(banner).getByRole('button', { name: 'Посмотреть день' }))
      expect(screen.getByRole('slider')).toHaveAttribute('aria-valuenow', '1')
    },
  )

  it('explains when the server returns no double or triple critical days', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const result = await serve(input).json()
        for (const point of result.points)
          point.critical = { level: 0, kind: 'none', crossings: [] }
        return Response.json(result)
      }),
    )
    mount()
    expect(
      await screen.findByRole('region', { name: 'Критические дни выбранного периода' }),
    ).toHaveTextContent('Двойных и тройных критических дней нет')
    expect(
      screen.queryByRole('region', { name: 'Двойной критический день' }),
    ).not.toBeInTheDocument()
  })

  it('loads server data, changes periods and splits three months into valid ranges', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => serve(input))
    vi.stubGlobal('fetch', fetchMock)
    mount()
    expect(screen.getByRole('status')).toHaveTextContent('Загружаем биоритмы')
    expect(await screen.findByRole('slider')).toHaveAttribute('aria-valuemax', '29')
    expect(screen.queryByText(/Демонстрационные/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: 'Неделя' }))
    await waitFor(() => expect(screen.getByRole('slider')).toHaveAttribute('aria-valuemax', '6'))
    await userEvent.click(screen.getByRole('radio', { name: '3 месяца' }))
    await waitFor(() => expect(screen.getByRole('slider')).toHaveAttribute('aria-valuemax', '91'))
    const urls = fetchMock.mock.calls.map(([input]) => new URL(String(input)))
    expect(
      urls.some(
        (url) =>
          url.searchParams.get('from') === '2026-11-01' &&
          url.searchParams.get('to') === '2027-01-01',
      ),
    ).toBe(true)
    expect(
      urls.some(
        (url) =>
          url.searchParams.get('from') === '2027-01-02' &&
          url.searchParams.get('to') === '2027-01-31',
      ),
    ).toBe(true)
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('Authorization')).toBe(
      'Bearer test-token',
    )
  })

  it('selects a forecast day and only shows cycle values and critical badges', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => serve(input)),
    )
    mount()
    await screen.findByRole('slider')
    const forecast = screen.getByRole('region', { name: 'Прогноз на 7 дней' })
    expect(within(forecast).getAllByRole('button')).toHaveLength(7)
    expect(forecast).not.toHaveTextContent('Интеллект: пик')
    await userEvent.click(within(forecast).getByRole('button', { name: 'Посмотреть 13 ноября' }))
    expect(screen.getByRole('slider')).toHaveAttribute('aria-valuenow', '12')
    expect(screen.getByRole('slider')).toHaveFocus()
    await userEvent.click(screen.getByRole('button', { name: 'О методике' }))
    expect(screen.getByText(/Классическая модель использует/)).toBeVisible()
  })

  it('shows errors without demo fallback and recovers on explicit retry', async () => {
    const fetchMock = vi.fn(async () => Response.json({}, { status: 503 }))
    vi.stubGlobal('fetch', fetchMock)
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent('Сервис временно недоступен')
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()
    fetchMock.mockImplementation(async (input?: RequestInfo | URL) => serve(input!))
    await userEvent.click(screen.getByRole('button', { name: 'Повторить запрос' }))
    expect(await screen.findByRole('slider')).toBeInTheDocument()
  })

  it('hides previous values while the next period loads and aborts obsolete requests', async () => {
    let pendingSignal: AbortSignal | null | undefined
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (new URL(String(input)).searchParams.get('from') === '2026-12-01') {
        pendingSignal = init?.signal
        return new Promise<Response>(() => {})
      }
      return serve(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    mount()
    await screen.findByRole('slider')
    await userEvent.click(screen.getByRole('button', { name: 'Следующий период' }))
    expect(screen.getByRole('status')).toHaveTextContent('Загружаем')
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Следующий период' }))
    await screen.findByRole('slider')
    expect(pendingSignal?.aborted).toBe(true)
    expect(screen.getByRole('group', { name: 'Навигация по периоду' })).toHaveTextContent(
      'январь 2027',
    )
  })

  it('discards personal data when the account changes', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => serve(input))
    vi.stubGlobal('fetch', fetchMock)
    mount()
    await screen.findByRole('slider')
    fetchMock.mockImplementation(async () => Response.json({}, { status: 503 }))
    act(() => useSessionStore.setState({ ownerId: 'owner-2', generation: 10 }))
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('rejects inconsistent calculation versions across chunks', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const result = serve(input)
        if (new URL(String(input)).searchParams.get('from') !== '2027-01-02') return result
        return Response.json({ ...(await result.json()), algorithm_version: '2.0.0' })
      }),
    )
    mount()
    await screen.findByRole('slider')
    await userEvent.click(screen.getByRole('radio', { name: '3 месяца' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Параметры расчёта изменились')
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()
  })

  it('shows server percentages without calculating substitute values', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const result = await serve(input).json()
        for (const point of result.points) {
          point.cycles.physical = { value: 0.123, percent: 12.3, phase: 'rising', trend: 'up' }
        }
        return Response.json(result)
      }),
    )
    mount()
    const slider = await screen.findByRole('slider')
    expect(slider.getAttribute('aria-valuetext')).toContain('+12,3 %')
    const forecast = screen.getByRole('region', { name: 'Прогноз на 7 дней' })
    expect(within(forecast).getAllByText('+12,3 %')).toHaveLength(7)
  })

  it('loads and focuses the correct period when a forecast day is outside the chart', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => serve(input)),
    )
    mount()
    await screen.findByRole('slider')
    await userEvent.click(screen.getByRole('button', { name: 'Следующий период' }))
    await screen.findByRole('slider')
    const forecast = screen.getByRole('region', { name: 'Прогноз на 7 дней' })
    await userEvent.click(within(forecast).getByRole('button', { name: 'Посмотреть 13 ноября' }))
    await waitFor(() => expect(screen.getByRole('slider')).toHaveFocus())
    expect(screen.getByRole('slider')).toHaveAttribute('aria-valuenow', '12')
  })

  it('rejects responses for a different profile timezone', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => serve(input)),
    )
    useSessionStore.setState({ timezone: 'UTC' })
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent('Часовой пояс профиля изменился')
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()
  })
})
