import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { useSessionStore, type SessionUser } from '@/stores/session'
import { renderWithProviders } from '@/test/renderWithProviders'
import { routes } from './routes'

const USER: SessionUser = { name: 'Анна', birthDate: null, chronotype: null }

type Visitor = 'guest' | 'new-user' | 'user'

function renderAt(path: string, visitor: Visitor, profile: Partial<SessionUser> = {}) {
  if (visitor !== 'guest') {
    useSessionStore.setState({
      accessToken: 'token',
      user: { ...USER, ...profile },
      onboarding: {
        ...useSessionStore.getInitialState().onboarding,
        birthDate: profile.birthDate ? profile.birthDate.split('-').reverse().join('.') : '',
      },
      isOnboarded: visitor === 'user',
    })
  }
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  renderWithProviders(<RouterProvider router={router} />)
  return router
}

describe('routes', () => {
  it.each([
    ['/login', 'guest', 1],
    ['/register', 'guest', 1],
    ['/onboarding/birth-date', 'new-user', 2],
    ['/onboarding/chronotype', 'new-user', 3],
    ['/onboarding/first-tasks', 'new-user', 4],
  ] as const)(
    'shows step %s in the shared four-step onboarding shell',
    async (path, visitor, step) => {
      renderAt(
        path,
        visitor,
        step > 2 ? { birthDate: '2003-09-20', chronotype: step > 3 ? 'lark' : null } : {},
      )

      const progress = await screen.findByRole('progressbar', { name: 'Онбординг' })
      expect(progress).toHaveAttribute('aria-valuenow', String(step))
      expect(progress).toHaveAttribute('aria-valuemax', '4')
      expect(progress).toHaveAttribute('aria-valuetext', `Шаг ${step} из 4`)
      expect(screen.getByRole('complementary', { name: 'Предпросмотр' })).toBeInTheDocument()
    },
  )

  it('sends guests to login', async () => {
    const router = renderAt('/calendar', 'guest')
    expect(await screen.findByRole('button', { name: 'Войти' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
  })

  it('sends a new user to onboarding after login', async () => {
    const router = renderAt('/calendar', 'guest')
    await userEvent.type(await screen.findByRole('textbox', { name: 'Email' }), 'anna@example.com')
    await userEvent.type(screen.getByLabelText('Пароль'), 'demo-password')
    await userEvent.click(await screen.findByRole('button', { name: 'Войти' }))
    expect(await screen.findByRole('heading', { name: 'Когда вы родились?' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/onboarding/birth-date')
    expect(useSessionStore.getState().accessToken).not.toBeNull()
  })

  it('walks through onboarding to today', async () => {
    const router = renderAt('/onboarding', 'new-user')
    await userEvent.type(
      await screen.findByRole('textbox', { name: 'Дата рождения' }),
      '20.09.2003',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Дальше' }))
    expect(
      await screen.findByRole('heading', { name: 'Когда вам легче думается?' }),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Дальше' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Добавить задачу' }))
    await userEvent.type(
      screen.getByRole('textbox', { name: 'Название задачи 1' }),
      'Подготовка к экзамену',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Составить план' }))
    await userEvent.click(screen.getAllByRole('button', { name: 'Открыть план' })[0])
    expect(await screen.findByRole('heading', { name: 'Сегодня' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/today')
    expect(useSessionStore.getState().isOnboarded).toBe(true)
  })

  it('keeps users without onboarding out of the app', async () => {
    const router = renderAt('/today', 'new-user')
    expect(await screen.findByRole('heading', { name: 'Когда вы родились?' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/onboarding/birth-date')
  })

  it('rejects an impossible birth date and focuses its field', async () => {
    const router = renderAt('/onboarding/birth-date', 'new-user')
    const input = await screen.findByRole('textbox', { name: 'Дата рождения' })
    await userEvent.type(input, '31.02.2003')
    await userEvent.click(screen.getByRole('button', { name: 'Дальше' }))
    expect(input).toHaveFocus()
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(router.state.location.pathname).toBe('/onboarding/birth-date')
  })

  it('retains birth time and chronotype when navigating backwards', async () => {
    renderAt('/onboarding/birth-date', 'new-user')
    await userEvent.type(
      await screen.findByRole('textbox', { name: 'Дата рождения' }),
      '29.02.2004',
    )
    await userEvent.type(
      screen.getByRole('textbox', { name: 'Время рождения · необязательно' }),
      '14:30',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Дальше' }))
    await userEvent.click(await screen.findByRole('radio', { name: /Сова/ }))
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Начало дня' }), '10:00')
    await userEvent.click(screen.getByRole('button', { name: 'Назад' }))
    expect(await screen.findByRole('textbox', { name: 'Дата рождения' })).toHaveValue('29.02.2004')
    expect(screen.getByRole('textbox', { name: 'Время рождения · необязательно' })).toHaveValue(
      '14:30',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Дальше' }))
    expect(await screen.findByRole('radio', { name: /Сова/ })).toBeChecked()
    expect(screen.getByRole('combobox', { name: 'Начало дня' })).toHaveValue('10:00')
  })

  it('prevents skipping required onboarding steps through the URL', async () => {
    const router = renderAt('/onboarding/first-tasks', 'new-user')
    expect(await screen.findByRole('textbox', { name: 'Дата рождения' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/onboarding/birth-date')
    expect(useSessionStore.getState().isOnboarded).toBe(false)
  })

  it('rejects a workday ending before it starts', async () => {
    const router = renderAt('/onboarding/chronotype', 'new-user', { birthDate: '2003-09-20' })
    const end = await screen.findByRole('combobox', { name: 'Конец дня' })
    await userEvent.selectOptions(end, '07:00')
    await userEvent.click(screen.getByRole('button', { name: 'Дальше' }))
    expect(end).toHaveFocus()
    expect(screen.getByRole('alert')).toHaveTextContent('позже начала')
    expect(router.state.location.pathname).toBe('/onboarding/chronotype')
  })

  it('requires named tasks and allows removing them without completing onboarding', async () => {
    renderAt('/onboarding/first-tasks', 'new-user', { birthDate: '2003-09-20', chronotype: 'lark' })
    await userEvent.click(await screen.findByRole('button', { name: 'Составить план' }))
    expect(screen.getByRole('alert')).toHaveTextContent('хотя бы одну')
    await userEvent.click(screen.getByRole('button', { name: 'Добавить задачу' }))
    await userEvent.click(screen.getByRole('button', { name: 'Составить план' }))
    expect(screen.getByRole('alert')).toHaveTextContent('название')
    await userEvent.click(screen.getByRole('button', { name: 'Удалить задачу 1' }))
    expect(screen.queryByRole('textbox', { name: 'Название задачи 1' })).not.toBeInTheDocument()
    expect(useSessionStore.getState().isOnboarded).toBe(false)
  })

  it('redirects onboarded users from login to today', async () => {
    const router = renderAt('/login', 'user')
    expect(await screen.findByRole('heading', { name: 'Сегодня' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/today')
  })

  it('redirects onboarded users from registration to today', async () => {
    const router = renderAt('/register', 'user')
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
