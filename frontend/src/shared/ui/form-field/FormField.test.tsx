import { createRef, useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FormMessage, SelectField, TextField } from './FormField'

describe('form fields', () => {
  it('keeps labels unique and associates hints, errors and external descriptions', async () => {
    render(
      <>
        <p id="policy">Данные профиля</p>
        <TextField
          label="Email"
          hint="Ваша почта"
          error="Проверьте email"
          aria-describedby="policy"
        />
        <TextField label="Другой email" />
      </>,
    )

    const email = screen.getByRole('textbox', { name: 'Email' })
    const other = screen.getByRole('textbox', { name: 'Другой email' })
    expect(email.id).not.toBe(other.id)
    expect(email).toHaveAttribute('aria-invalid', 'true')
    expect(email).toHaveAccessibleDescription('Данные профиля Ваша почта Проверьте email')
    await userEvent.click(screen.getByText('Email', { selector: 'label' }))
    expect(email).toHaveFocus()
  })

  it('removes obsolete error descriptions while preserving input and ref access', async () => {
    const ref = createRef<HTMLInputElement>()
    const { rerender } = render(<TextField label="Задача" error="Введите название" ref={ref} />)
    await userEvent.type(screen.getByRole('textbox', { name: 'Задача' }), 'Курсовая')

    rerender(<TextField label="Задача" hint="До 200 символов" ref={ref} />)

    expect(ref.current).toHaveValue('Курсовая')
    expect(ref.current).not.toHaveAttribute('aria-invalid')
    expect(ref.current).toHaveAccessibleDescription('До 200 символов')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('supports controlled selection and keyboard focus', async () => {
    function Example() {
      const [start, setStart] = useState('08:00')
      return (
        <SelectField
          label="Начало дня"
          value={start}
          onChange={(event) => setStart(event.target.value)}
        >
          <option value="08:00">08:00</option>
          <option value="09:00">09:00</option>
        </SelectField>
      )
    }

    render(<Example />)
    const select = screen.getByRole('combobox', { name: 'Начало дня' })
    await userEvent.tab()
    expect(select).toHaveFocus()
    await userEvent.selectOptions(select, '09:00')
    expect(select).toHaveValue('09:00')
  })

  it('leaves disabled controls unchanged and out of the tab order', async () => {
    const onChange = vi.fn()
    render(
      <>
        <TextField label="Недоступно" defaultValue="Сохранено" onChange={onChange} disabled />
        <SelectField label="Режим" defaultValue="lark" onChange={onChange} disabled>
          <option value="lark">Жаворонок</option>
          <option value="owl">Сова</option>
        </SelectField>
        <TextField label="Доступно" />
      </>,
    )

    await userEvent.type(screen.getByRole('textbox', { name: 'Недоступно' }), 'Новое')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Режим' }), 'owl')
    await userEvent.tab()

    expect(screen.getByRole('textbox', { name: 'Доступно' })).toHaveFocus()
    expect(screen.getByRole('textbox', { name: 'Недоступно' })).toHaveValue('Сохранено')
    expect(screen.getByRole('combobox', { name: 'Режим' })).toHaveValue('lark')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('announces form errors and informational results with appropriate roles', () => {
    render(
      <>
        <FormMessage>Нет связи с сервером</FormMessage>
        <FormMessage tone="success">Почта подтверждена</FormMessage>
      </>,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('Нет связи с сервером')
    expect(screen.getByRole('status')).toHaveTextContent('Почта подтверждена')
  })
})
