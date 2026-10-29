import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as Segment from './Segment'

function ScaleSegment() {
  const [value, setValue] = useState('week')
  return (
    <Segment.Root value={value} onValueChange={setValue} aria-label="Масштаб">
      <Segment.Item value="day">День</Segment.Item>
      <Segment.Item value="week">Неделя</Segment.Item>
      <Segment.Item value="month">Месяц</Segment.Item>
    </Segment.Root>
  )
}

describe('Segment', () => {
  it('marks the selected item', () => {
    render(<ScaleSegment />)
    expect(screen.getByRole('radio', { name: 'Неделя' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: 'День' })).toHaveAttribute('aria-checked', 'false')
  })

  it('selects item on click', async () => {
    render(<ScaleSegment />)
    await userEvent.click(screen.getByRole('radio', { name: 'Месяц' }))
    expect(screen.getByRole('radio', { name: 'Месяц' })).toHaveAttribute('aria-checked', 'true')
  })

  it('moves selection with arrow keys', async () => {
    render(<ScaleSegment />)
    await userEvent.tab()
    expect(screen.getByRole('radio', { name: 'Неделя' })).toHaveFocus()
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('radio', { name: 'Месяц' })).toHaveAttribute('aria-checked', 'true')
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('radio', { name: 'День' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: 'День' })).toHaveFocus()
  })

  it('throws when item is rendered outside root', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<Segment.Item value="day">День</Segment.Item>)).toThrow(
      'Segment.Item must be rendered inside Segment.Root',
    )
  })
})
