import { StrictMode, useState } from 'react'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DAILY_SCHEDULE_FIXTURES, PLANNING_FIXTURE_CONTEXT } from '@/shared/fixtures/planning'
import { mockMatchMedia } from '@/test/matchMedia'
import { EditTaskDialog } from './EditTaskDialog'
import type { TaskFormOptions } from './taskFormSettings'

const task = DAILY_SCHEDULE_FIXTURES.normal.tasks[2]
const context = {
  timezone: PLANNING_FIXTURE_CONTEXT.timezone,
  now: new Date(PLANNING_FIXTURE_CONTEXT.now),
  workStart: '08:00',
  workEnd: '18:00',
}
const options: TaskFormOptions = {
  recurrence: { frequency: 'weekly', interval: 2, weekdays: [1, 3, 5], until: '2026-12-30' },
  reminderMinutes: 15,
}

describe('task editing dialog', () => {
  it('prefills task fields in the profile timezone and preserves additional settings', async () => {
    render(<EditTaskDialog task={task} context={context} options={options} onCancel={vi.fn()} />)
    expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue(task.title)
    expect(screen.getByRole('textbox', { name: 'Название' })).toHaveFocus()
    expect(screen.getByRole('textbox', { name: /Описание/ })).toHaveValue(task.description)
    expect(screen.getByRole('radio', { name: '1,5 ч' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Интеллектуальная' })).toBeChecked()
    expect(screen.getByLabelText('Дата дедлайна')).toHaveValue('2026-11-11')
    expect(screen.getByLabelText('Время дедлайна')).toHaveValue('14:00')
    expect(screen.getByRole('button', { name: 'Сохранить изменения' })).toBeDisabled()
    expect(screen.queryByRole('region', { name: 'Предложенное время' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Ещё:/ }))
    expect(screen.getByRole('radio', { name: 'Высокий' })).toBeChecked()
    expect(screen.getByLabelText('Время начала')).toHaveValue('10:00')
    expect(screen.getByRole('radio', { name: 'Свой график…' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Пн' })).toBeChecked()
    expect(screen.getByRole('combobox', { name: 'Напоминание' })).toHaveValue('15')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('prepares an update with its original version and explicit nullable field clearing', async () => {
    const submit = vi.fn()
    render(
      <EditTaskDialog
        task={task}
        context={context}
        options={options}
        onCancel={vi.fn()}
        onSubmit={submit}
      />,
    )
    await userEvent.clear(screen.getByRole('textbox', { name: /Описание/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Очистить дедлайн' }))
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({
        version: task.version,
        description: null,
        deadline: null,
        title: task.title,
      }),
      options,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Изменения ещё не сохранены в плане')
    expect(task.description).not.toBeNull()
    expect(task.deadline).not.toBeNull()
    expect(fetch).not.toHaveBeenCalled()
    await userEvent.type(screen.getByRole('textbox', { name: 'Название' }), ' — новое')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('allows unpinning without retaining the old timestamp', async () => {
    const submit = vi.fn()
    render(
      <EditTaskDialog
        task={DAILY_SCHEDULE_FIXTURES.normal.tasks[4]}
        context={context}
        onCancel={vi.fn()}
        onSubmit={submit}
      />,
    )
    expect(screen.getByRole('switch', { name: 'Закрепить время' })).toBeChecked()
    expect(screen.getByLabelText('Время закрепления')).toHaveValue('15:00')
    await userEvent.click(screen.getByRole('switch', { name: 'Закрепить время' }))
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({ is_pinned: false, pinned_start: null }),
      expect.any(Object),
    )
  })

  it('uses mobile field order, expands additional fields and submits a custom duration', async () => {
    mockMatchMedia(false)
    const submit = vi.fn()
    render(
      <EditTaskDialog
        task={{ ...task, duration_min: 75 }}
        options={options}
        context={context}
        onCancel={vi.fn()}
        onSubmit={submit}
      />,
    )
    const types = screen.getByRole('radiogroup', { name: /Тип/ })
    const duration = screen.getByRole('spinbutton', { name: 'Длительность в минутах' })
    expect(types.compareDocumentPosition(duration) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(duration).toHaveValue(75)
    expect(screen.queryByRole('textbox', { name: /Описание/ })).not.toBeInTheDocument()
    const additional = screen.getByRole('button', { name: /Дополнительно/ })
    await userEvent.click(additional)
    expect(additional).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('textbox', { name: /Описание/ })).toHaveValue(task.description)
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Напоминание' }), '30')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ duration_min: 75 }), {
      ...options,
      reminderMinutes: 30,
    })
  })

  it('validates edited fields and focuses the first invalid control', async () => {
    const submit = vi.fn()
    render(
      <EditTaskDialog
        task={{ ...task, duration_min: 75 }}
        context={context}
        onCancel={vi.fn()}
        onSubmit={submit}
      />,
    )
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Длительность в минутах' }), {
      target: { value: '4' },
    })
    fireEvent.submit(screen.getByRole('form', { name: 'Редактирование задачи' }))
    expect(screen.getByRole('alert')).toHaveTextContent('от 5 до 480')
    await waitFor(() => expect(screen.getByRole('spinbutton')).toHaveFocus())
    expect(submit).not.toHaveBeenCalled()
  })

  it('resets the form and preview when another task or a newer version is opened', async () => {
    const cancel = vi.fn()
    const { rerender } = render(<EditTaskDialog task={task} context={context} onCancel={cancel} />)
    await userEvent.type(screen.getByRole('textbox', { name: 'Название' }), ' новое')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))
    expect(screen.getByRole('status')).toBeInTheDocument()
    rerender(
      <EditTaskDialog
        task={{ ...task, version: task.version + 1, title: 'Новая версия' }}
        context={context}
        onCancel={cancel}
      />,
    )
    expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue('Новая версия')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Сохранить изменения' })).toBeDisabled()
  })

  it('traps keyboard focus and restores it to the opening button after Escape', async () => {
    function Example() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button data-task-edit-trigger onClick={() => setOpen(true)}>
            Редактировать
          </button>
          {open ? (
            <EditTaskDialog task={task} context={context} onCancel={() => setOpen(false)} />
          ) : null}
        </>
      )
    }
    render(
      <StrictMode>
        <Example />
      </StrictMode>,
    )
    const trigger = screen.getByRole('button', { name: 'Редактировать' })
    await userEvent.click(trigger)
    const dialog = screen.getByRole('dialog')
    await userEvent.type(screen.getByRole('textbox', { name: 'Название' }), ' новое')
    const last = within(dialog).getByRole('button', { name: 'Сохранить изменения' })
    act(() => last.focus())
    fireEvent.keyDown(dialog, { key: 'Tab' })
    expect(within(dialog).getAllByRole('button')[0]).toHaveFocus()
    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true })
    expect(last).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    expect(document.body.style.overflow).toBe('')
  })
})
