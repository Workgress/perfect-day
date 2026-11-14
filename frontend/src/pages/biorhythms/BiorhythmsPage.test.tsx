import { useState } from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BIORHYTHM_FIXTURES } from '@/shared/fixtures/biorhythms'
import { BiorhythmChart } from './BiorhythmChart'
import { BiorhythmsPage } from './BiorhythmsPage'

function Chart() {
  const [at, setAt] = useState<string | null>(BIORHYTHM_FIXTURES.week.points[0].at)
  return <BiorhythmChart data={BIORHYTHM_FIXTURES.week} selectedAt={at} onSelect={setAt} />
}

describe('biorhythm chart interactions', () => {
  it('selects points using the keyboard and exposes percentages as accessible text', async () => {
    render(<Chart />)
    const slider = screen.getByRole('slider', { name: 'Дата на графике биоритмов' })
    slider.focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(slider).toHaveAttribute('aria-valuenow', '1')
    expect(slider.getAttribute('aria-valuetext')).toContain('Физический:')
    await userEvent.keyboard('{End}')
    expect(slider).toHaveAttribute('aria-valuenow', '6')
    await userEvent.keyboard('{ArrowRight}')
    expect(slider).toHaveAttribute('aria-valuenow', '6')
    await userEvent.keyboard('{Home}')
    expect(slider).toHaveAttribute('aria-valuenow', '0')
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('toggles curves independently and explains an empty selection', async () => {
    const { container } = render(<Chart />)
    const legend = screen.getByRole('group', { name: 'Отображаемые циклы' })
    const buttons = within(legend).getAllByRole('button')
    await userEvent.click(buttons[0])
    expect(buttons[0]).toHaveAttribute('aria-pressed', 'false')
    expect(container.querySelectorAll('path[data-cycle]')).toHaveLength(2)
    await userEvent.click(buttons[1])
    await userEvent.click(buttons[2])
    expect(screen.getByRole('status')).toHaveTextContent('Выберите хотя бы один цикл')
    await userEvent.click(buttons[0])
    expect(container.querySelectorAll('path[data-cycle]')).toHaveLength(1)
  })

  it('toggles critical day shading without hiding curves and exposes a data table', async () => {
    const { container } = render(<Chart />)
    expect(container.querySelectorAll('[data-critical-date]').length).toBeGreaterThan(0)
    await userEvent.click(screen.getByRole('switch', { name: 'Показывать критические дни' }))
    expect(container.querySelectorAll('[data-critical-date]')).toHaveLength(0)
    expect(container.querySelectorAll('path[data-cycle]')).toHaveLength(3)
    await userEvent.click(screen.getByText('Значения в таблице'))
    expect(screen.getByRole('table')).toBeVisible()
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(8)
  })

  it('shows an empty state and supports data appearing later', () => {
    const { rerender } = render(
      <BiorhythmChart
        data={{ ...BIORHYTHM_FIXTURES.week, points: [] }}
        selectedAt={null}
        onSelect={vi.fn()}
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Нет данных')
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()
    rerender(<BiorhythmChart data={BIORHYTHM_FIXTURES.week} selectedAt={null} onSelect={vi.fn()} />)
    expect(screen.getByRole('slider')).toBeInTheDocument()
  })
})

describe('biorhythm forecast page', () => {
  it('marks demo data and changes periods, including a three-month view', async () => {
    render(<BiorhythmsPage />)
    expect(screen.getByText(/Демонстрационные данные/)).toBeInTheDocument()
    expect(screen.getByRole('slider')).toHaveAttribute('aria-valuemax', '29')
    await userEvent.click(screen.getByRole('radio', { name: 'Неделя' }))
    expect(screen.getByRole('slider')).toHaveAttribute('aria-valuemax', '6')
    await userEvent.click(screen.getByRole('radio', { name: '3 месяца' }))
    expect(screen.getByRole('slider')).toHaveAttribute('aria-valuemax', '91')
    await userEvent.click(screen.getByRole('button', { name: 'Следующий период' }))
    expect(screen.getByRole('group', { name: 'Навигация по периоду' })).toHaveTextContent('февр.')
    await userEvent.click(screen.getByRole('button', { name: 'Предыдущий период' }))
    expect(screen.getByRole('group', { name: 'Навигация по периоду' })).toHaveTextContent('нояб.')
  })

  it('selects a forecast day on the plot and expands the methodology', async () => {
    render(<BiorhythmsPage />)
    const forecast = screen.getByRole('region', { name: 'Прогноз на 7 дней' })
    const day = within(forecast).getByRole('button', { name: 'Посмотреть 13 ноября' })
    await userEvent.click(day)
    expect(day).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('slider')).toHaveAttribute('aria-valuenow', '12')
    expect(screen.getByRole('slider')).toHaveFocus()
    await userEvent.click(screen.getByRole('button', { name: 'О методике' }))
    expect(screen.getByText(/Классическая модель использует/)).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Свернуть' }))
    expect(screen.getByText(/Классическая модель использует/)).not.toBeVisible()
  })

  it('does not request or fabricate personal API data while laying out the screen', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(<BiorhythmsPage />)
    fireEvent.keyDown(screen.getByRole('slider'), { key: 'ArrowRight' })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
