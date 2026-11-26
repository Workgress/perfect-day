import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { createQueryClient } from '@/shared/api/queryClient'
import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import type { SavedSchedule } from '@/shared/model/schedule'
import { useSessionStore } from '@/stores/session'
import { DeadlineAvailability, hasDeadlineWindow } from './DeadlineAvailability'
import { TodayPlanSummary } from './TodayPlanSummary'
import { TodayDayEnd } from './TodayDayEnd'
import { ReplanReview, scheduleChanges } from './ReplanReview'
import { TodayLoading } from './TodayLoading'

vi.mock('./useTodayBiorhythms', () => ({
  useTodayBiorhythms: () => ({ data: undefined, isError: false }),
}))
const day = DAILY_SCHEDULE_FIXTURES.normal
const context = { timezone: day.timezone, workStart: '08:00', workEnd: '18:00' }
const at = (clock: string) => Date.parse(`${day.date}T${clock}:00+05:00`)
function saved(slots: SavedSchedule['slots'] = []): SavedSchedule {
  return {
    id: day.schedule!.id,
    planned_date: day.date,
    timezone: day.timezone,
    version: 1,
    algorithm_version: 'test',
    generated_at: new Date(at('08:00')).toISOString(),
    slots,
    unscheduled: [],
    warnings: [],
    moves: [],
    metrics: {
      requested_min: 60,
      planned_min: 60,
      capacity_min: 600,
      high_intensity_min: 0,
      critical_level: 0,
      load_factor: 1,
      moved_min: 0,
    },
  }
}
function occupied(start: string, end: string): SavedSchedule['slots'][number] {
  return {
    id: day.slots[0].id,
    kind: 'task',
    task_id: day.tasks[2].id,
    start_at: new Date(at(start)).toISOString(),
    end_at: new Date(at(end)).toISOString(),
    explanation: null,
    is_pinned: true,
    reason_codes: [],
  }
}
function setup(element: React.ReactNode) {
  useSessionStore
    .getState()
    .signIn({
      accessToken: 'states-test',
      user: { name: 'Анна', birthDate: '2003-09-20', chronotype: 'lark' },
    })
  const client = createQueryClient()
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{element}</MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...view, client }
}

describe('Today loading and day end', () => {
  afterEach(() => vi.useRealTimers())
  it('shows a labelled loading skeleton without interactive placeholder tasks', () => {
    setup(<TodayLoading />)
    expect(screen.getByRole('status', { name: 'Загружаем план дня' })).toHaveAttribute(
      'aria-busy',
      'true',
    )
    expect(screen.getByText('Раскладываем задачи по окнам…')).toBeVisible()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
  it('shows the day end after work and counts actual completions without marking remaining tasks done', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(at('19:00')))
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json({ items: [], total: 0, limit: 100, offset: 0 })),
    )
    const { client } = setup(<TodayPlanSummary day={day} />)
    const summary = screen.getByRole('region', { name: 'Итог дня' })
    expect(summary).toHaveTextContent(
      `${day.tasks.filter((task) => task.status === 'done').length} из ${day.tasks.length}`,
    )
    expect(summary).toHaveTextContent('Без выполнения:')
    expect(screen.queryByRole('button', { name: 'Начать' })).not.toBeInTheDocument()
    await screen.findByText('Задач в плане: 0.')
    client.clear()
  })
  it('stores the selected feeling for this day and never sends it to the server', async () => {
    const request = vi.fn<typeof fetch>(async () =>
      Response.json({ items: [], total: 0, limit: 100, offset: 0 }),
    )
    vi.stubGlobal('fetch', request)
    const { client, unmount } = setup(<TodayDayEnd day={day} />)
    await userEvent.click(screen.getByRole('radio', { name: '4 из 5' }))
    expect(screen.getByRole('radio', { name: '4 из 5' })).toBeChecked()
    expect(screen.getByRole('status')).toHaveTextContent('Сохранено на этом устройстве.')
    expect(request.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(
      true,
    )
    await screen.findByText('Задач в плане: 0.')
    const key = Object.keys(localStorage).find((item) => item.startsWith('perfect-day:feeling:'))!
    expect(localStorage.getItem(key)).toBe('4')
    unmount()
    client.clear()
    localStorage.removeItem(key)
  })
})

describe('deadline availability', () => {
  it('accepts an exact fit starting now between occupied intervals', () => {
    expect(
      hasDeadlineWindow(
        [
          {
            date: day.date,
            schedule: saved([occupied('08:00', '10:00'), occupied('10:31', '18:00')]),
          },
        ],
        context,
        30,
        at('10:31'),
        at('10:01'),
      ),
    ).toBe(true)
  })
  it('does not combine fragmented gaps or use time after the deadline', () => {
    expect(
      hasDeadlineWindow(
        [
          {
            date: day.date,
            schedule: saved([occupied('08:20', '09:00'), occupied('09:20', '18:00')]),
          },
        ],
        context,
        30,
        at('09:30'),
        at('08:00'),
      ),
    ).toBe(false)
  })
  it('considers a free later day before the deadline', () => {
    expect(
      hasDeadlineWindow(
        [
          { date: day.date, schedule: saved([occupied('08:00', '18:00')]) },
          { date: '2026-11-12', schedule: null },
        ],
        context,
        60,
        Date.parse('2026-11-12T12:00:00+05:00'),
        at('08:00'),
      ),
    ).toBe(true)
  })
  it('shows the design warning without pretending that the scheduler cannot move flexible tasks', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json(saved([occupied('08:00', '18:00')]))),
    )
    const { client } = setup(
      <DeadlineAvailability
        context={context}
        date={day.date}
        duration={60}
        deadline={`${day.date}T18:00`}
        now={new Date(at('08:00'))}
      />,
    )
    expect(await screen.findByRole('status', { name: 'Проверка срока' })).toHaveTextContent(
      'Нет свободного окна',
    )
    expect(screen.getByText(/проверит возможность сдвинуть/)).toBeVisible()
    client.clear()
  })
  it('does not turn server failures into a no-free-window warning', async () => {
    const request = vi.fn(async () =>
      Response.json({ error: { code: 'SERVER_ERROR', message: 'Ошибка' } }, { status: 503 }),
    )
    vi.stubGlobal('fetch', request)
    const { client } = setup(
      <DeadlineAvailability
        context={context}
        date={day.date}
        duration={60}
        deadline={`${day.date}T18:00`}
        now={new Date(at('08:00'))}
      />,
    )
    await waitFor(() => expect(client.isFetching()).toBe(0))
    expect(request).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('Нет свободного окна')).not.toBeInTheDocument()
    client.clear()
  })
})

describe('saved replan changes', () => {
  it('detects added, removed and moved intervals and ignores id/offset-only changes', () => {
    const before = saved([occupied('10:00', '11:00')])
    const after = saved([
      { ...occupied('10:00', '11:00'), id: 'new-slot', start_at: `${day.date}T10:00:00+05:00` },
    ])
    expect(scheduleChanges(before, after)).toEqual([])
    after.slots[0] = occupied('12:00', '13:00')
    expect(scheduleChanges(before, after)).toHaveLength(1)
    expect(scheduleChanges(before, saved())[0].after).toEqual([])
    expect(scheduleChanges(undefined, after)[0].before).toEqual([])
  })
  it('clearly reports an unchanged plan after saving without offering a false apply action', () => {
    setup(
      <ReplanReview
        review={{ before: saved(), after: saved() }}
        tasks={day.tasks}
        now={new Date(at('09:00'))}
        onClose={vi.fn()}
      />,
    )
    const dialog = screen.getByRole('dialog', { name: 'Результат перепланирования' })
    expect(dialog).toHaveTextContent('Изменения уже сохранены.')
    expect(dialog).toHaveTextContent('Время задач не изменилось')
    expect(within(dialog).getAllByRole('button')).toHaveLength(1)
  })
})
