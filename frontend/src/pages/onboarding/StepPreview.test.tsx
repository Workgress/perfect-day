import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { useSessionStore } from '@/stores/session'
import { ChronotypePage } from './ChronotypePage'
import { DayWindowsPreview } from './StepPreview'

describe('day windows preview', () => {
  it('updates activity windows immediately on chronotype and workday changes', async () => {
    useSessionStore.getState().signIn({
      accessToken: 'test',
      user: { name: 'Анна', birthDate: '2003-09-20', chronotype: null },
    })
    const user = userEvent.setup()
    render(
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
