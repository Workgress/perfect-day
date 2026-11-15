import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { DailyTimeline } from './DailyTimeline'
import { TimelinePreviewPage } from './TimelinePreviewPage'

const now = new Date('2026-11-11T04:42:00Z')
const normal = DAILY_SCHEDULE_FIXTURES.normal

describe('daily timeline', () => {
  it('shows four distinct task types and separates breaks, lunch and rest', () => {
    const { container } = render(<DailyTimeline day={normal} now={now} />)
    for (const type of ['intellectual', 'creative', 'physical', 'routine']) {
      expect(container.querySelector(`[data-kind="task"][data-type="${type}"]`)).toBeInTheDocument()
    }
    for (const kind of ['break', 'lunch', 'rest']) {
      expect(container.querySelector(`[data-kind="${kind}"]`)).toHaveAttribute('data-type', 'rest')
    }
    const exam = screen.getByRole('article', { name: /^Подготовка к экзамену/ })
    expect(exam).toHaveTextContent('10:00–11:30')
    expect(exam.parentElement).toHaveStyle({ height: '108px' })
    expect(screen.getByLabelText('Сейчас 09:42')).toBeInTheDocument()
  })

  it('opens a task from the keyboard and exposes the full long title', async () => {
    const select = vi.fn()
    render(<DailyTimeline day={normal} now={now} onTaskSelect={select} />)
    const task = normal.tasks[3]
    const button = within(screen.getByRole('list', { name: 'Интервалы расписания' })).getByRole(
      'button',
      { name: new RegExp(`^${task.title}`) },
    )
    button.focus()
    await userEvent.keyboard('{Enter}')
    expect(select).toHaveBeenCalledWith(task)
    expect(button.getAttribute('aria-label')).toContain('Творческая')
  })

  it('expands completed tasks and collapses them without changing the remaining intervals', async () => {
    render(<DailyTimeline day={normal} now={now} />)
    expect(screen.queryByRole('article', { name: /^Разобрать почту/ })).not.toBeInTheDocument()
    const completed = screen.getByRole('button', { name: /Выполнено: 2/ })
    await userEvent.click(completed)
    expect(completed).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('article', { name: /^Разобрать почту/ })).toHaveTextContent(
      '08:00–08:30',
    )
    await userEvent.click(completed)
    expect(screen.queryByRole('article', { name: /^Разобрать почту/ })).not.toBeInTheDocument()
    expect(screen.getByRole('article', { name: /^Подготовка к экзамену/ })).toHaveTextContent(
      '10:00–11:30',
    )
  })

  it('shows an empty day with the hour scale and an add-task action', async () => {
    const create = vi.fn()
    const { container } = render(
      <DailyTimeline day={DAILY_SCHEDULE_FIXTURES.empty} now={now} onCreateTask={create} />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('На этот день задач нет')
    expect(screen.getByText('08:00')).toBeInTheDocument()
    expect(screen.getByText('18:00')).toBeInTheDocument()
    expect(container.querySelectorAll('[data-slot-id]')).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: 'Добавить задачу' }))
    expect(create).toHaveBeenCalledWith('2026-11-11')
  })

  it('starts a new task from a genuine free hour', async () => {
    const create = vi.fn()
    render(<DailyTimeline day={normal} now={now} onCreateTask={create} />)
    await userEvent.click(
      screen.getByRole('button', { name: /Добавить задачу: Свободно 17:00–18:00/ }),
    )
    expect(create).toHaveBeenCalledWith('2026-11-11', '17:00')
  })

  it('keeps very short tasks accessible in the full interval list', async () => {
    const day = structuredClone(normal)
    day.slots = [
      { ...day.slots[2], start_at: '2026-11-11T05:00:00Z', end_at: '2026-11-11T05:05:00Z' },
    ]
    const select = vi.fn()
    render(<DailyTimeline day={day} now={now} onTaskSelect={select} />)
    const card = screen.getByRole('button', { name: /^Подготовка к экзамену\. 10:00–10:05/ })
    expect(card.parentElement).toHaveStyle({ height: '6px' })
    await userEvent.click(screen.getByText('Все интервалы списком'))
    await userEvent.click(screen.getByRole('button', { name: 'Подготовка к экзамену' }))
    expect(select).toHaveBeenCalledWith(day.tasks[2])
  })

  it('shows a readable error for an invalid interval', () => {
    render(<DailyTimeline day={{ ...normal, tasks: [] }} now={now} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Не удалось показать план дня')
  })

  it('switches demo days and reuses the editor and creation forms without writing to the API', async () => {
    render(<TimelinePreviewPage />)
    await userEvent.click(screen.getByRole('button', { name: /^Подготовка к экзамену\./ }))
    expect(screen.getByRole('dialog', { name: 'Подготовка к экзамену' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Название' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Изменить' }))
    expect(screen.getByRole('dialog', { name: 'Редактировать задачу' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue('Подготовка к экзамену')
    await userEvent.keyboard('{Escape}')
    expect(screen.getByRole('dialog', { name: 'Подготовка к экзамену' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    await userEvent.click(screen.getByRole('radio', { name: 'Пустой день' }))
    await userEvent.click(screen.getByRole('button', { name: 'Добавить задачу' }))
    expect(screen.getByRole('dialog', { name: 'Новая задача' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('radio', { name: 'Перегруженный день' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Импортировать из календаря' }))
    expect(screen.getByText('Импорт из календаря пока не подключён.')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })
})
