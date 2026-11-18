import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TASK_FORM_FIXTURES } from '@/shared/fixtures/planning'
import { TaskForm } from './TaskForm'
import { mockMatchMedia } from '@/test/matchMedia'

const context = {
  timezone: 'Asia/Yekaterinburg',
  workStart: '08:00',
  workEnd: '18:00',
  now: new Date('2026-11-11T04:42:00Z'),
}

describe('task creation form', () => {
  it('shows required errors and focuses the first invalid field', async () => {
    const onSubmit = vi.fn()
    render(<TaskForm context={context} onCancel={vi.fn()} onSubmit={onSubmit} />)
    expect(screen.getByRole('button', { name: 'Добавить и распределить' })).toBeDisabled()
    fireEvent.submit(screen.getByRole('form'))
    expect(screen.getAllByRole('alert')).toHaveLength(3)
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Название' })).toHaveFocus())
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('submits a manually entered duration and a type selected with the keyboard', async () => {
    const onSubmit = vi.fn()
    render(<TaskForm context={context} onCancel={vi.fn()} onSubmit={onSubmit} />)
    await userEvent.type(screen.getByRole('textbox', { name: 'Название' }), 'Презентация')
    const types = screen.getByRole('radiogroup', { name: /Тип/ })
    within(types).getByRole('radio', { name: 'Интеллектуальная' }).focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(within(types).getByRole('radio', { name: 'Творческая' })).toBeChecked()
    await userEvent.click(
      within(screen.getByRole('radiogroup', { name: /Длительность/ })).getByRole('radio', {
        name: 'Другое…',
      }),
    )
    const duration = screen.getByRole('spinbutton', { name: 'Длительность в минутах' })
    await waitFor(() => expect(duration).toHaveFocus())
    await userEvent.type(duration, '75')
    await userEvent.click(screen.getByRole('button', { name: /Ещё:/ }))
    await userEvent.click(screen.getByRole('radio', { name: 'Высокий' }))
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Презентация',
        duration_min: 75,
        type: 'creative',
        priority: 'high',
      }),
      expect.objectContaining({ reminderMinutes: 5 }),
    )
  })

  it('requires both deadline parts and allows clearing the deadline', async () => {
    const onSubmit = vi.fn()
    render(
      <TaskForm
        context={context}
        initialValues={{ ...TASK_FORM_FIXTURES.edit, deadlineLocal: '' }}
        onCancel={vi.fn()}
        onSubmit={onSubmit}
      />,
    )
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /Срок/ }), 'date')
    fireEvent.change(screen.getByLabelText('Дата дедлайна'), { target: { value: '2026-11-12' } })
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    expect(screen.getByRole('alert')).toHaveTextContent('дату и время полностью')
    expect(onSubmit).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Время дедлайна'), { target: { value: '14:00' } })
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    expect(onSubmit).toHaveBeenLastCalledWith(
      expect.objectContaining({ deadline: '2026-11-12T09:00:00.000Z' }),
      expect.any(Object),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Очистить дедлайн' }))
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    expect(onSubmit).toHaveBeenLastCalledWith(
      expect.objectContaining({ deadline: null }),
      expect.any(Object),
    )
  })

  it('requires an explicit pinned time and clears it when pinning is disabled', async () => {
    const onSubmit = vi.fn()
    render(
      <TaskForm
        context={context}
        initialValues={{ ...TASK_FORM_FIXTURES.edit, deadlineLocal: '' }}
        onCancel={vi.fn()}
        onSubmit={onSubmit}
      />,
    )
    await userEvent.click(screen.getByRole('switch', { name: 'Закрепить время' }))
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    expect(screen.getByRole('alert')).toHaveTextContent('дату и время полностью')
    fireEvent.change(screen.getByLabelText('Время закрепления'), { target: { value: '15:00' } })
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    expect(onSubmit).toHaveBeenLastCalledWith(
      expect.objectContaining({ is_pinned: true, pinned_start: '2026-11-11T10:00:00.000Z' }),
      expect.any(Object),
    )
    await userEvent.click(screen.getByRole('switch', { name: 'Закрепить время' }))
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    expect(onSubmit).toHaveBeenLastCalledWith(
      expect.objectContaining({ is_pinned: false, pinned_start: null }),
      expect.any(Object),
    )
  })

  it('keeps mobile fields in design order and preserves additional settings when collapsed', async () => {
    mockMatchMedia(false)
    const onSubmit = vi.fn()
    render(
      <TaskForm
        context={context}
        initialValues={{ ...TASK_FORM_FIXTURES.edit, deadlineLocal: '' }}
        onCancel={vi.fn()}
        onSubmit={onSubmit}
      />,
    )
    expect(screen.queryByRole('switch', { name: 'Закрепить время' })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Описание/ })).not.toBeInTheDocument()
    const form = screen.getByRole('form')
    const title = screen.getByRole('textbox', { name: 'Название' })
    const type = screen.getByRole('radiogroup', { name: /Тип/ })
    const duration = screen.getByRole('radiogroup', { name: /Длительность/ })
    const deadline = screen.getByRole('combobox', { name: /Срок/ })
    for (const [before, after] of [
      [title, type],
      [type, duration],
      [duration, deadline],
    ])
      expect(before.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: /Дополнительно/ }))
    const priority = screen.getByRole('radiogroup', { name: 'Приоритет' })
    const preferred = screen.getByRole('combobox', { name: /Желаемое время/ })
    const repeat = screen.getByRole('radiogroup', { name: 'Повторять' })
    const pin = screen.getByRole('switch', { name: 'Закрепить время' })
    const reminder = screen.getByRole('combobox', { name: 'Напоминание' })
    const description = screen.getByRole('textbox', { name: /Описание/ })
    for (const [before, after] of [
      [priority, preferred],
      [preferred, repeat],
      [repeat, pin],
      [pin, reminder],
      [reminder, description],
    ])
      expect(before.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await userEvent.click(within(repeat).getByRole('radio', { name: 'Каждый день' }))
    await userEvent.selectOptions(reminder, '15')
    await userEvent.click(screen.getByRole('button', { name: /Дополнительно/ }))
    expect(screen.queryByRole('combobox', { name: 'Напоминание' })).not.toBeInTheDocument()
    expect(form).toContainElement(screen.getByRole('region', { name: 'Предложенное время' }))
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    expect(onSubmit).toHaveBeenCalledWith(expect.any(Object), {
      recurrence: { frequency: 'daily', interval: 1, weekdays: [], until: null },
      reminderMinutes: 15,
    })
  })

  it('reopens mobile additional settings for an invalid custom schedule and submits selected weekdays', async () => {
    mockMatchMedia(false)
    const onSubmit = vi.fn()
    render(
      <TaskForm
        context={context}
        initialValues={{ ...TASK_FORM_FIXTURES.edit, deadlineLocal: '' }}
        onCancel={vi.fn()}
        onSubmit={onSubmit}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: /Дополнительно/ }))
    await userEvent.click(screen.getByRole('radio', { name: 'Свой график…' }))
    await userEvent.click(screen.getByRole('button', { name: /Дополнительно/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    expect(screen.getByRole('button', { name: /Дополнительно/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(screen.getByRole('alert')).toHaveTextContent('хотя бы один день')
    expect(onSubmit).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('checkbox', { name: 'Пн' }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Пт' }))
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Интервал в неделях' }), {
      target: { value: '2' },
    })
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Напоминание' }), '')
    await userEvent.click(screen.getByRole('button', { name: 'Добавить и распределить' }))
    expect(onSubmit).toHaveBeenCalledWith(expect.any(Object), {
      recurrence: { frequency: 'weekly', interval: 2, weekdays: [1, 5], until: null },
      reminderMinutes: null,
    })
  })

  it('displays the supplied suggestion and opens the preferred time controls', async () => {
    render(
      <TaskForm
        context={context}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
        suggestion={{
          startsAt: '2026-11-12T06:00:00Z',
          endsAt: '2026-11-12T07:00:00Z',
          explanation: 'Подходящее окно для творческой задачи.',
        }}
      />,
    )
    const suggestion = screen.getByRole('region', { name: 'Предложенное время' })
    expect(suggestion).toHaveTextContent('11:00–12:00')
    expect(suggestion).toHaveTextContent('Подходящее окно для творческой задачи.')
    await userEvent.click(screen.getByRole('button', { name: /Выбрать другое время/ }))
    await waitFor(() => expect(screen.getByLabelText('Время начала')).toHaveFocus())
  })
})
