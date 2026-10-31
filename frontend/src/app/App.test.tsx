import { render, screen } from '@testing-library/react'
import { App } from './App'

describe('App', () => {
  it('opens login for a guest', async () => {
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Войти' })).toBeInTheDocument()
  })
})
