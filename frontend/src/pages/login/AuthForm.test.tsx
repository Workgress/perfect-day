import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { useSessionStore } from '@/stores/session'
import { renderWithProviders } from '@/test/renderWithProviders'
import { AuthError, resendConfirmation, submitAuth, type AuthResult } from './auth'
import { LoginPage } from './LoginPage'

vi.mock('./auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./auth')>()),
  submitAuth: vi.fn(),
  resendConfirmation: vi.fn(),
}))

const SESSION: AuthResult = {
  status: 'authenticated',
  session: {
    accessToken: 'test-token',
    user: { name: 'Анна', birthDate: null, chronotype: null },
  },
}

function renderPage(path = '/login', state?: unknown) {
  const router = createMemoryRouter(
    [
      { path: '/login', element: <LoginPage /> },
      { path: '/register', element: <LoginPage /> },
      { path: '/today', element: <h1>План</h1> },
    ],
    { initialEntries: [{ pathname: path, state }] },
  )
  const view = renderWithProviders(<RouterProvider router={router} />)
  return { ...view, router }
}

async function fillForm(
  user: ReturnType<typeof userEvent.setup>,
  email = 'anna@example.com',
  password = 'demo-password',
) {
  await user.type(screen.getByRole('textbox', { name: 'Email' }), email)
  await user.type(screen.getByLabelText('Пароль'), password)
}

beforeEach(() => {
  vi.mocked(submitAuth).mockReset().mockResolvedValue(SESSION)
  vi.mocked(resendConfirmation).mockReset().mockResolvedValue(60)
})

describe('auth forms', () => {
  it('validates registration fields before requesting and focuses the first error', async () => {
    const user = userEvent.setup()
    renderPage('/register')
    await fillForm(user, 'invalid-email', 'short')
    await user.click(screen.getByRole('button', { name: 'Создать аккаунт' }))

    expect(submitAuth).not.toHaveBeenCalled()
    expect(screen.getByRole('textbox', { name: 'Email' })).toHaveFocus()
    expect(screen.getByText('Проверьте адрес почты')).toBeInTheDocument()
    expect(screen.getByText('Используйте не менее 8 символов')).toBeInTheDocument()
  })

  it('submits by Enter, trims email and preserves password whitespace', async () => {
    const user = userEvent.setup()
    renderPage()
    await fillForm(user, ' anna@example.com ', '  secret  ')
    await user.keyboard('{Enter}')

    expect(await screen.findByRole('heading', { name: 'План' })).toBeInTheDocument()
    expect(submitAuth).toHaveBeenCalledWith(
      'login',
      {
        email: 'anna@example.com',
        password: '  secret  ',
      },
      expect.any(AbortSignal),
    )
    expect(useSessionStore.getState().accessToken).toBe('test-token')
  })

  it('retains email but clears the password and validation when switching modes', async () => {
    const user = userEvent.setup()
    const { router } = renderPage()
    await fillForm(user)
    await user.click(screen.getByRole('link', { name: 'Создать аккаунт' }))

    expect(router.state.location.pathname).toBe('/register')
    expect(screen.getByRole('textbox', { name: 'Email' })).toHaveValue('anna@example.com')
    expect(screen.getByLabelText('Пароль')).toHaveValue('')
    expect(screen.getByLabelText('Пароль')).toHaveAttribute('autocomplete', 'new-password')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    await user.type(screen.getByLabelText('Пароль'), 'register-password')
    await user.click(screen.getByRole('link', { name: 'Войти' }))

    expect(router.state.location.pathname).toBe('/login')
    expect(screen.getByRole('textbox', { name: 'Email' })).toHaveValue('anna@example.com')
    expect(screen.getByLabelText('Пароль')).toHaveValue('')
    expect(screen.getByLabelText('Пароль')).toHaveAttribute('autocomplete', 'current-password')
  })

  it('prevents duplicate requests while submitting', async () => {
    let finish!: (result: AuthResult) => void
    vi.mocked(submitAuth).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve
      }),
    )
    const user = userEvent.setup()
    renderPage()
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Войти' }))

    expect(screen.getByRole('textbox', { name: 'Email' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Входим…' })).toBeDisabled()
    fireEvent.submit(screen.getByRole('form', { name: 'Вход по почте' }))
    expect(submitAuth).toHaveBeenCalledTimes(1)

    await act(async () => finish(SESSION))
    expect(await screen.findByRole('heading', { name: 'План' })).toBeInTheDocument()
  })

  it('keeps entered values after failure and never falls back to registration', async () => {
    vi.mocked(submitAuth).mockRejectedValue(new AuthError('Неверный email или пароль'))
    const user = userEvent.setup()
    renderPage()
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Войти' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Неверный email или пароль')
    expect(screen.getByLabelText('Пароль')).toHaveValue('demo-password')
    expect(screen.getByRole('textbox', { name: 'Email' })).toHaveValue('anna@example.com')
    expect(useSessionStore.getState().accessToken).toBeNull()
    expect(submitAuth).toHaveBeenCalledTimes(1)
    expect(vi.mocked(submitAuth).mock.calls[0][0]).toBe('login')
  })

  it('focuses server field errors after the controls are re-enabled', async () => {
    vi.mocked(submitAuth).mockRejectedValue(
      new AuthError('Адрес занят', { email: 'Выберите другой email' }),
    )
    const user = userEvent.setup()
    renderPage('/register')
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Создать аккаунт' }))

    expect(await screen.findByText('Выберите другой email')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Email' })).toHaveFocus()
    expect(screen.getByRole('textbox', { name: 'Email' })).not.toBeDisabled()
  })

  it('shows confirmation without signing in and rate-limits resend', async () => {
    vi.mocked(submitAuth).mockResolvedValue({
      status: 'verification_required',
      resendAfterSeconds: 1,
    })
    const user = userEvent.setup()
    renderPage('/register')
    await fillForm(user, 'new@example.com')
    await user.click(screen.getByRole('button', { name: 'Создать аккаунт' }))

    expect(await screen.findByRole('heading', { name: 'Проверьте почту' })).toHaveFocus()
    expect(screen.getByText('new@example.com', { selector: 'strong' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Отправить ещё раз' })).toBeDisabled()
    expect(useSessionStore.getState().accessToken).toBeNull()
    await waitFor(
      () => expect(screen.getByRole('button', { name: 'Отправить ещё раз' })).toBeEnabled(),
      { timeout: 1500 },
    )
    await user.click(screen.getByRole('button', { name: 'Отправить ещё раз' }))
    expect(resendConfirmation).toHaveBeenCalledWith('new@example.com', expect.any(AbortSignal))
    expect(screen.getByRole('button', { name: 'Отправить ещё раз' })).toBeDisabled()
  })

  it('aborts a pending request on navigation and ignores its late success', async () => {
    let finish!: (result: AuthResult) => void
    vi.mocked(submitAuth).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve
      }),
    )
    const user = userEvent.setup()
    const { router } = renderPage()
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Войти' }))
    const signal = vi.mocked(submitAuth).mock.calls[0][2]

    await act(async () => {
      await router.navigate('/register')
    })
    expect(signal.aborted).toBe(true)
    await act(async () => finish(SESSION))
    expect(router.state.location.pathname).toBe('/register')
    expect(useSessionStore.getState().accessToken).toBeNull()
  })

  it('does not claim success for unavailable providers or password recovery', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByRole('button', { name: 'Продолжить с Google' }))
    expect(screen.getByRole('status')).toHaveTextContent('пока недоступен')
    await user.click(screen.getByRole('button', { name: 'Забыли пароль?' }))
    expect(screen.getByRole('status')).toHaveTextContent('Восстановление пароля пока недоступно')
    expect(submitAuth).not.toHaveBeenCalled()
    expect(useSessionStore.getState().accessToken).toBeNull()
  })
})
