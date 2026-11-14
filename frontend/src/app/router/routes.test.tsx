import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { useSessionStore, type SessionUser } from '@/stores/session'
import { renderWithProviders } from '@/test/renderWithProviders'
import { routes } from './routes'
import { installApiServer, profileFixture } from '@/test/apiServer'

const USER: SessionUser = { name: 'Анна', birthDate: null, chronotype: null }

type Visitor = 'guest' | 'new-user' | 'user'

function renderAt(path: string, visitor: Visitor, profile: Partial<SessionUser> = {}) {
  const document = profileFixture({ ...USER, ...profile }, visitor === 'user')
  installApiServer(document, visitor !== 'guest')
  if (visitor !== 'guest') {
    useSessionStore.getState().signIn({ accessToken: 'token' })
    useSessionStore.getState().applyProfile(document)
  }
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  renderWithProviders(<RouterProvider router={router} />)
  return router
}

describe('routes', () => {
  it('opens the task editing preview when the backend is unavailable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Offline')
      }),
    )
    const router = createMemoryRouter(routes, { initialEntries: ['/dev/tasks/edit'] })
    renderWithProviders(<RouterProvider router={router} />)
    expect(await screen.findByRole('dialog', { name: 'Редактировать задачу' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue('Подготовка к экзамену')
    expect(
      screen.queryByRole('heading', { name: 'Не удалось загрузить данные' }),
    ).not.toBeInTheDocument()
  })

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

      const preview = await screen.findByRole('complementary', { name: 'Предпросмотр' })
      const progress = screen.getByRole('progressbar', { name: 'Онбординг' })
      expect(progress).toHaveAttribute('aria-valuenow', String(step))
      expect(progress).toHaveAttribute('aria-valuemax', '4')
      expect(progress).toHaveAttribute('aria-valuetext', `Шаг ${step} из 4`)
      expect(preview).toBeInTheDocument()
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
    expect(await screen.findByRole('heading', { name: 'Сегодня' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/today')
    expect(useSessionStore.getState().isOnboarded).toBe(true)
  })

  it('keeps users without onboarding out of the app', async () => {
    const router = renderAt('/today', 'new-user')
    expect(await screen.findByRole('heading', { name: 'Когда вы родились?' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/onboarding/birth-date')
  })

  it('restores an existing session and opens the requested URL after reload', async () => {
    installApiServer(profileFixture({}, true), true)
    const router = createMemoryRouter(routes, {
      initialEntries: ['/calendar?date=2026-11-06#week'],
    })
    renderWithProviders(<RouterProvider router={router} />)
    expect(await screen.findByRole('heading', { name: 'Календарь' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/calendar')
    expect(router.state.location.search).toBe('?date=2026-11-06')
    expect(router.state.location.hash).toBe('#week')
    expect(localStorage.getItem('pd-session')).not.toContain('refreshed-token')
  })

  it('resumes the next onboarding step returned by the server', async () => {
    installApiServer(profileFixture({ birthDate: '2003-09-20', chronotype: null }), true)
    const router = createMemoryRouter(routes, { initialEntries: ['/today'] })
    renderWithProviders(<RouterProvider router={router} />)
    expect(
      await screen.findByRole('heading', { name: 'Когда вам легче думается?' }),
    ).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/onboarding/chronotype')
  })

  it('opens local onboarding when the profile API is missing', async () => {
    const base = installApiServer(profileFixture(), true)
    vi.stubGlobal(
      'fetch',
      vi.fn((input: URL, init?: RequestInit) =>
        String(input).endsWith('/auth/refresh')
          ? Promise.resolve(
              Response.json({
                access_token: `header.${btoa(JSON.stringify({ sub: 'local-user' }))}.signature`,
                token_type: 'bearer',
                expires_in: 900,
              }),
            )
          : String(input).endsWith('/me')
            ? Promise.resolve(
                Response.json(
                  { error: { code: 'NOT_FOUND', message: 'Маршрут профиля ещё не реализован' } },
                  { status: 404 },
                ),
              )
            : base(input, init),
      ),
    )
    const router = createMemoryRouter(routes, { initialEntries: ['/today'] })
    renderWithProviders(<RouterProvider router={router} />)
    expect(await screen.findByRole('heading', { name: 'Когда вы родились?' })).toBeInTheDocument()
    expect(useSessionStore.getState().user?.id).toBe('local-user')
    expect(useSessionStore.getState().isLocalProfile).toBe(true)
    expect(useSessionStore.getState().isOnboarded).toBe(false)
    expect(screen.queryByRole('heading', { name: 'Сегодня' })).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('preserves the tasks and idempotency key when completion fails and is retried', async () => {
    const router = renderAt('/onboarding/first-tasks', 'new-user', {
      birthDate: '2003-09-20',
      chronotype: 'lark',
    })
    const base = vi.mocked(fetch)
    const attempts: RequestInit[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: URL, init?: RequestInit) => {
        if (String(input).endsWith('/onboarding/complete')) {
          attempts.push(init!)
          if (attempts.length === 1)
            return Promise.resolve(
              Response.json(
                { error: { code: 'SERVICE_UNAVAILABLE', message: 'Попробуйте ещё раз' } },
                { status: 503 },
              ),
            )
        }
        return base(input, init)
      }),
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Добавить задачу' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Название задачи 1' }), 'Учёба')
    await userEvent.click(screen.getByRole('button', { name: 'Составить план' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Попробуйте ещё раз')
    expect(useSessionStore.getState().isOnboarded).toBe(false)
    expect(screen.getByRole('textbox', { name: 'Название задачи 1' })).toHaveValue('Учёба')
    await userEvent.click(screen.getByRole('button', { name: 'Составить план' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/today'))
    expect(new Headers(attempts[0].headers).get('Idempotency-Key')).toBe(
      new Headers(attempts[1].headers).get('Idempotency-Key'),
    )
    expect(attempts[0].body).toBe(attempts[1].body)
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
    expect(screen.queryByRole('textbox', { name: 'Часовой пояс рождения' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Дальше' }))
    await userEvent.click(await screen.findByRole('radio', { name: /Сова/ }))
    const profileCall = vi
      .mocked(fetch)
      .mock.calls.find(([url]) => String(url).endsWith('/me/profile'))
    expect(JSON.parse(String(profileCall?.[1]?.body))).toEqual({
      birth_date: '2004-02-29',
      birth_time: '14:30:00',
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    })
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
    renderAt('/today', 'user')
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )
    expect(await screen.findByText('Нет связи с сервером')).toBeInTheDocument()
  })
})
