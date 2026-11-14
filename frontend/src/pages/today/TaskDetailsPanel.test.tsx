import { StrictMode, useState } from 'react'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { TaskDetailsPanel } from './TaskDetailsPanel'

const day = DAILY_SCHEDULE_FIXTURES.normal
const task = day.tasks[2]
const now = new Date('2026-11-11T04:42:00Z')
const base = {
  task,
  slots: day.slots,
  timezone: day.timezone,
  now,
  onClose: vi.fn(),
  onEdit: vi.fn(),
}

describe('task details panel', () => {
  it('shows the task details and real placement explanations without opening editable fields', () => {
    render(<TaskDetailsPanel {...base} options={{ recurrence: null, reminderMinutes: 10 }} />)
    const panel = screen.getByRole('dialog', { name: task.title })
    expect(within(panel).getByRole('heading', { name: task.title })).toHaveFocus()
    expect(panel).toHaveTextContent('10:00–11:30')
    expect(panel).toHaveTextContent('90 мин')
    expect(panel).toHaveTextContent('сегодня, до 14:00')
    expect(panel).toHaveTextContent('Высокий')
    expect(panel).toHaveTextContent('Не повторять')
    expect(panel).toHaveTextContent('За 10 минут до начала')
    expect(screen.getByRole('region', { name: 'Почему в это время' })).toHaveTextContent(
      'После задачи — перерыв 30 мин',
    )
    expect(panel).not.toHaveTextContent('+95')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('opens editing and delegates the other actions without saving to the API', async () => {
    const edit = vi.fn()
    const move = vi.fn()
    const pin = vi.fn()
    const start = vi.fn()
    render(<TaskDetailsPanel {...base} onEdit={edit} onMove={move} onPin={pin} onStart={start} />)
    await userEvent.click(screen.getByRole('button', { name: 'Изменить' }))
    await userEvent.click(screen.getByRole('button', { name: 'Перенести' }))
    await userEvent.click(screen.getByRole('button', { name: 'Закрепить' }))
    await userEvent.click(screen.getByRole('button', { name: 'Начать сейчас' }))
    for (const callback of [edit, move, pin, start]) expect(callback).toHaveBeenCalledOnce()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('shows an unplaced task without inventing a time or placement explanation', () => {
    render(<TaskDetailsPanel {...base} task={DAILY_SCHEDULE_FIXTURES.overloaded.tasks[7]} />)
    expect(screen.getByRole('dialog')).toHaveTextContent('Время не назначено')
    expect(screen.getByRole('dialog')).toHaveTextContent('не распределено')
    expect(screen.getByRole('button', { name: 'Начать сейчас' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Закрепить' })).toBeDisabled()
    expect(screen.getByRole('region', { name: 'Почему в это время' })).toHaveTextContent(
      'пока не размещена на шкале',
    )
  })

  it('recognizes pinned and completed task states', () => {
    const { rerender } = render(<TaskDetailsPanel {...base} task={day.tasks[4]} onPin={vi.fn()} />)
    expect(screen.getByRole('dialog')).toHaveTextContent('время закреплено')
    expect(screen.getByRole('button', { name: 'Открепить' })).toBeEnabled()
    rerender(<TaskDetailsPanel {...base} task={day.tasks[0]} onStart={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Выполнена' })).toBeDisabled()
  })

  it('closes on Escape and restores focus and scrolling to the selected task', async () => {
    function Example() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button data-task-details-trigger onClick={() => setOpen(true)}>
            Открыть задачу
          </button>
          {open ? <TaskDetailsPanel {...base} onClose={() => setOpen(false)} /> : null}
        </>
      )
    }
    render(
      <StrictMode>
        <Example />
      </StrictMode>,
    )
    const trigger = screen.getByRole('button', { name: 'Открыть задачу' })
    await userEvent.click(trigger)
    expect(document.body.style.overflow).toBe('hidden')
    const panel = screen.getByRole('dialog')
    act(() => screen.getByRole('button', { name: 'Изменить' }).focus())
    fireEvent.keyDown(panel, { key: 'Tab' })
    expect(screen.getByRole('button', { name: 'Закрыть задачу' })).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    expect(document.body.style.overflow).toBe('')
  })
})
