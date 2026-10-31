import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Button } from './Button'

describe('Button', () => {
  it('uses primary medium button by default', () => {
    render(<Button>Добавить</Button>)
    const button = screen.getByRole('button', { name: 'Добавить' })
    expect(button).toHaveAttribute('type', 'button')
    expect(button).toHaveAttribute('data-variant', 'primary')
    expect(button).toHaveAttribute('data-size', 'm')
  })

  it('applies variant and size', () => {
    render(
      <Button variant="ghost" size="s">
        Перенести
      </Button>,
    )
    const button = screen.getByRole('button', { name: 'Перенести' })
    expect(button).toHaveAttribute('data-variant', 'ghost')
    expect(button).toHaveAttribute('data-size', 's')
  })

  it('does not fire click when disabled', async () => {
    const onClick = vi.fn()
    render(
      <Button disabled onClick={onClick}>
        Сохранить
      </Button>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    expect(onClick).not.toHaveBeenCalled()
  })
})
