import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Toggle } from './Toggle'

function ControlledToggle() {
  const [checked, setChecked] = useState(false)
  return <Toggle aria-label="Итог дня" checked={checked} onCheckedChange={setChecked} />
}

describe('Toggle', () => {
  it('switches state on click', async () => {
    render(<ControlledToggle />)
    const toggle = screen.getByRole('switch', { name: 'Итог дня' })
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-checked', 'true')
  })

  it('ignores clicks when disabled', async () => {
    const onCheckedChange = vi.fn()
    render(<Toggle aria-label="Сон" checked={false} onCheckedChange={onCheckedChange} disabled />)
    await userEvent.click(screen.getByRole('switch', { name: 'Сон' }))
    expect(onCheckedChange).not.toHaveBeenCalled()
  })
})
