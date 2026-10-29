import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import type { SessionState } from '@/app/session/SessionContext'
import { SessionProvider } from '@/app/session/SessionProvider'
import { routes } from './routes'

const GUEST: SessionState = { isAuthenticated: false, isOnboarded: false, userName: null }
const NEW_USER: SessionState = { isAuthenticated: true, isOnboarded: false, userName: 'Анна' }
const USER: SessionState = { isAuthenticated: true, isOnboarded: true, userName: 'Анна' }

function renderAt(path: string, session: SessionState) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(
    <SessionProvider initialState={session}>
      <RouterProvider router={router} />
    </SessionProvider>,
  )
  return router
}

describe('routes', () => {
  it('sends guests to login', async () => {
    const router = renderAt('/calendar', GUEST)
    expect(await screen.findByRole('button', { name: 'Войти' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
  })

  it('sends a new user to onboarding after login', async () => {
    const router = renderAt('/calendar', GUEST)
    await userEvent.click(await screen.findByRole('button', { name: 'Войти' }))
    expect(await screen.findByRole('heading', { name: 'Дата рождения' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/onboarding/birth-date')
  })

  it('walks through onboarding to today', async () => {
    const router = renderAt('/onboarding', NEW_USER)
    await userEvent.click(await screen.findByRole('button', { name: 'Далее' }))
    expect(await screen.findByRole('heading', { name: 'Хронотип и режим' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Далее' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Готово' }))
    expect(await screen.findByRole('heading', { name: 'Сегодня' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/today')
  })

  it('keeps users without onboarding out of the app', async () => {
    const router = renderAt('/today', NEW_USER)
    expect(await screen.findByRole('heading', { name: 'Дата рождения' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/onboarding/birth-date')
  })

  it('redirects onboarded users from login and onboarding to today', async () => {
    const router = renderAt('/login', USER)
    expect(await screen.findByRole('heading', { name: 'Сегодня' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/today')
  })

  it('redirects root to today', async () => {
    const router = renderAt('/', USER)
    expect(await screen.findByRole('heading', { name: 'Сегодня' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/today')
  })

  it('navigates through the sidebar and marks the active item', async () => {
    renderAt('/today', USER)
    await userEvent.click(await screen.findByRole('link', { name: 'Биоритмы' }))
    expect(await screen.findByRole('heading', { name: 'Биоритмы' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Биоритмы' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Сегодня' })).not.toHaveAttribute('aria-current')
  })

  it('opens and closes new task over today', async () => {
    const router = renderAt('/today', USER)
    await userEvent.click(await screen.findByRole('button', { name: 'Добавить задачу' }))
    expect(await screen.findByRole('dialog', { name: 'Новая задача' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Сегодня' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(router.state.location.pathname).toBe('/today')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('signs out back to login', async () => {
    const router = renderAt('/settings', USER)
    await userEvent.click(await screen.findByRole('button', { name: 'Выйти' }))
    expect(await screen.findByRole('button', { name: 'Войти' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
  })

  it('shows 404 for unknown paths', async () => {
    renderAt('/unknown', GUEST)
    expect(await screen.findByRole('heading', { name: 'Страница не найдена' })).toBeInTheDocument()
  })
})
