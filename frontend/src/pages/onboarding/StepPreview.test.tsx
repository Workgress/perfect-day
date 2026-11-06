import { screen, within } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { useSessionStore } from '@/stores/session'
import { ChronotypePage } from './ChronotypePage'
import { DayWindowsPreview, FirstTasksPreview } from './StepPreview'

describe('day windows preview', () => {
  it('updates activity windows immediately on chronotype and workday changes', async () => {
    useSessionStore.getState().signIn({
      accessToken: 'test',
      user: { name: 'Анна', birthDate: '2003-09-20', chronotype: null },
    })
    const user = userEvent.setup()
    renderWithProviders(
      <MemoryRouter>
        <ChronotypePage />
        <DayWindowsPreview />
      </MemoryRouter>,
    )
    const preview = screen.getByRole('region', { name: 'Окна вашего дня' })
    expect(
      within(preview).getByTitle('Интеллектуальное окно · пик 10–12: 10:00–12:00'),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: /Голубь/ }))
    expect(
      within(preview).getByTitle('Интеллектуальное окно · пик 11–13: 11:00–13:00'),
    ).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Начало дня' })).toHaveValue('09:00')
    expect(screen.getByRole('combobox', { name: 'Конец дня' })).toHaveValue('19:00')
    expect(screen.getByRole('combobox', { name: 'Отбой' })).toHaveValue('23:30')
    expect(
      within(preview).queryByTitle('Интеллектуальное окно · пик 10–12: 10:00–12:00'),
    ).not.toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: /Сова/ }))
    expect(
      within(preview).getByTitle('Интеллектуальное окно · пик 14–16: 14:00–16:00'),
    ).toBeInTheDocument()
    expect(
      within(preview).getByTitle('Разгон: почта, планирование: 12:00–14:00'),
    ).toBeInTheDocument()
    expect(within(preview).getByTitle('Вторая волна: 17:00–18:30')).toBeInTheDocument()
    expect(within(preview).getByTitle('Физическое окно: 19:00–20:00')).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Начало дня' })).toHaveValue('12:00')
    expect(screen.getByRole('combobox', { name: 'Конец дня' })).toHaveValue('22:00')
    expect(screen.getByRole('combobox', { name: 'Отбой' })).toHaveValue('01:00')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Начало дня' }), '15:30')
    expect(
      within(preview).getByTitle('Интеллектуальное окно · пик 14–16: 15:30–16:00'),
    ).toBeInTheDocument()

    await user.selectOptions(screen.getByRole('combobox', { name: 'Конец дня' }), '15:00')
    expect(within(preview).getByText('Выберите конец дня позже начала.')).toBeInTheDocument()
    expect(within(preview).queryByTitle(/Интеллектуальное окно/)).not.toBeInTheDocument()
  })
})

describe('first tasks preview', () => {
  beforeEach(() => {
    useSessionStore.getState().signIn({ accessToken: 'test' })
    useSessionStore.getState().updateOnboarding({
      tasks: [
        { id: 'exam', title: 'Подготовка к экзамену', type: 'intellectual', durationMin: 90 },
      ],
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json({ error: { code: 'NOT_FOUND' } }, { status: 404 })),
    )
  })

  it('renders the local time, title and explanation in design order', async () => {
    renderWithProviders(<FirstTasksPreview />)
    const time = await screen.findByText('10:00–11:30')
    const title = screen.getByText('Подготовка к экзамену')
    const explanation = screen.getByText(/Предварительно: интеллектуальное окно/)
    expect(time.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(
      title.compareDocumentPosition(explanation) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    expect(screen.getByText(/Биоритмы пока не учитываются/)).toBeInTheDocument()
    expect(screen.queryByText('Готово')).not.toBeInTheDocument()
  })

  it('uses the server time and explanation when the preview API is available', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: URL | string, init?: RequestInit) => {
        const body = JSON.parse(String(init?.body))
        return Response.json({
          planned_date: body.planned_date,
          timezone: 'UTC',
          slots: [
            {
              task_index: 0,
              start_time: '13:00:00',
              end_time: '14:30:00',
              explanation: 'Вторая волна концентрации после обеда',
            },
          ],
          unscheduled_task_indexes: [],
        })
      }),
    )
    renderWithProviders(<FirstTasksPreview />)
    expect(await screen.findByText('13:00–14:30')).toBeInTheDocument()
    expect(screen.getByText('Вторая волна концентрации после обеда')).toBeInTheDocument()
    expect(screen.queryByText(/Биоритмы пока не учитываются/)).not.toBeInTheDocument()
  })

  it('shows a retry action on server failures without local successful slots', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        Response.json(
          { error: { code: 'PLANNER_UNAVAILABLE', message: 'Планировщик недоступен' } },
          { status: 503 },
        ),
      ),
    )
    renderWithProviders(<FirstTasksPreview />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Планировщик недоступен')
    expect(screen.getByRole('button', { name: 'Повторить расчёт' })).toBeInTheDocument()
    expect(screen.queryByText('10:00–11:30')).not.toBeInTheDocument()
  })
})
