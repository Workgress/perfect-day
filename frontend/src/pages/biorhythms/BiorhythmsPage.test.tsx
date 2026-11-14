import { useState } from 'react'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BIORHYTHM_FIXTURES } from '@/shared/fixtures/biorhythms'
import { BiorhythmChart } from './BiorhythmChart'

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
