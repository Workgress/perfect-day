import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { useSessionStore, type SessionUser } from '@/stores/session'
import { renderWithProviders } from '@/test/renderWithProviders'
import { routes } from './routes'

const USER: SessionUser = { name: 'Анна', birthDate: null, chronotype: null }

type Visitor = 'guest' | 'new-user' | 'user'

function renderAt(path: string, visitor: Visitor) {
  if (visitor !== 'guest') {
    useSessionStore.setState({
      accessToken: 'token',
      user: USER,
      isOnboarded: visitor === 'user',
    })
  }
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  renderWithProviders(<RouterProvider router={router} />)
  return router
}

describe('routes', () => {
  it('sends guests to login', async () => {
    const router = renderAt('/calendar', 'guest')
    expect(await screen.findByRole('button', { name: 'Войти' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
  })

  it('sends a new user to onboarding after login', async () => {
    const router = renderAt('/calendar', 'guest')
    await userEvent.click(await screen.findByRole('button', { name: 'Войти' }))
    expect(await screen.findByRole('heading', { name: 'Дата рождения' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/onboarding/birth-date')
    expect(useSessionStore.getState().accessToken).not.toBeNull()
  })

  it('walks through onboarding to today', async () => {
    const router = renderAt('/onboarding', 'new-user')
    await userEvent.click(await screen.findByRole('button', { name: 'Далее' }))
    expect(await screen.findByRole('heading', { name: 'Хронотип и режим' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Далее' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Готово' }))
    expect(await screen.findByRole('heading', { name: 'Сегодня' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/today')
    expect(useSessionStore.getState().isOnboarded).toBe(true)
  })

  it('keeps users without onboarding out of the app', async () => {
    const router = renderAt('/today', 'new-user')
    expect(await screen.findByRole('heading', { name: 'Дата рождения' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/onboarding/birth-date')
  })

  it('redirects onboarded users from login to today', async () => {
    const router = renderAt('/login', 'user')
    expect(await screen.findByRole('heading', { name: 'Сегодня' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/today')
  })

  it('redirects root to today', async () => {
    const router = renderAt('/', 'user')
    expect(await screen.findByRole('heading', { name: 'Сегодня' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/today')
  })

  it('navigates through the sidebar and marks the active item', async () => {
    renderAt('/today', 'user')
    await userEvent.click(await screen.findByRole('link', { name: 'Биоритмы' }))
    expect(await screen.findByRole('heading', { name: 'Биоритмы' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Биоритмы' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Сегодня' })).not.toHaveAttribute('aria-current')
  })

  it('opens and closes new task over today', async () => {
    const router = renderAt('/today', 'user')
    await userEvent.click(await screen.findByRole('button', { name: 'Добавить задачу' }))
    expect(await screen.findByRole('dialog', { name: 'Новая задача' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Сегодня' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(router.state.location.pathname).toBe('/today')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('signs out back to login', async () => {
    const router = renderAt('/settings', 'user')
    await userEvent.click(await screen.findByRole('button', { name: 'Выйти' }))
    expect(await screen.findByRole('button', { name: 'Войти' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
    expect(useSessionStore.getState().accessToken).toBeNull()
  })

  it('shows 404 for unknown paths', async () => {
    renderAt('/unknown', 'guest')
    expect(await screen.findByRole('heading', { name: 'Страница не найдена' })).toBeInTheDocument()
  })

  it('shows that the server is available', async () => {
    renderAt('/today', 'user')
    expect(await screen.findByText('Сервер доступен')).toBeInTheDocument()
  })

  it('shows that the server is unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )
    renderAt('/today', 'user')
    expect(await screen.findByText('Нет связи с сервером')).toBeInTheDocument()
  })
})
