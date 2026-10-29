import { render, screen } from '@testing-library/react'
import { App } from './App'

describe('App', () => {
  it('renders the UI kit in both themes', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Тёмная тема' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Светлая тема' })).toBeInTheDocument()
  })
})
