import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { useSessionStore } from '@/stores/session'
import { renderWithProviders } from '@/test/renderWithProviders'
import { AuthError, resendConfirmation, submitAuth, type AuthResult } from './auth'
import { LoginPage } from './LoginPage'
import { EmailSentPage } from './EmailSentPage'

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
      { path: '/verify-email/sent', element: <EmailSentPage /> },
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
  password = 'Testpass123',
) {
  await user.type(screen.getByRole('textbox', { name: 'Электронная почта' }), email)
  await user.type(screen.getByLabelText('Пароль'), password)
  const confirm = screen.queryByLabelText('Повторите пароль')
  if (confirm) fireEvent.change(confirm, { target: { value: password } })
}

beforeEach(() => {
  vi.mocked(submitAuth).mockReset().mockResolvedValue(SESSION)
  vi.mocked(resendConfirmation).mockReset().mockResolvedValue(60)
})

describe('auth forms', () => {
  afterEach(() => vi.useRealTimers())

  it('shows the registration design and rejects a mismatched confirmation before POST', async () => {
    const user = userEvent.setup()
    renderPage('/register')
    expect(screen.getByRole('heading', { name: 'Создайте аккаунт' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Продолжить с Google' })).not.toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    await fillForm(user)
    await user.clear(screen.getByLabelText('Повторите пароль'))
    await user.type(screen.getByLabelText('Повторите пароль'), 'Different123')
    await user.click(screen.getByRole('button', { name: 'Создать аккаунт' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Пароли не совпадают.')
    expect(screen.getByLabelText('Повторите пароль')).toHaveFocus()
    expect(screen.getByLabelText('Повторите пароль')).toHaveAttribute('aria-invalid', 'true')
    expect(submitAuth).not.toHaveBeenCalled()
  })

  it('shows the Figma credential error and respects the server retry interval without queued requests', async () => {
    const user = userEvent.setup()
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-26T10:00:00Z'))
    vi.mocked(submitAuth)
      .mockRejectedValueOnce(new AuthError('backend error', {}, 'INVALID_CREDENTIALS'))
      .mockRejectedValueOnce(new AuthError('limited', {}, 'RATE_LIMIT_EXCEEDED', 2))
    renderPage()
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Войти' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Неверная почта или пароль. Проверьте данные.',
    )
    await user.click(screen.getByRole('button', { name: 'Войти' }))
    expect(await screen.findByText('Слишком много попыток входа')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Повторить через 00:02' })).toBeDisabled()
    fireEvent.submit(screen.getByRole('form', { name: 'Вход по почте' }))
    expect(submitAuth).toHaveBeenCalledTimes(2)
    vi.setSystemTime(new Date('2026-11-26T10:00:03Z'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Войти' })).toBeEnabled(), {
      timeout: 1500,
    })
    expect(submitAuth).toHaveBeenCalledTimes(2)
  })
  it('validates registration fields before requesting and focuses the first error', async () => {
    const user = userEvent.setup()
    renderPage('/register')
    await fillForm(user, 'invalid-email', 'short')
    await user.click(screen.getByRole('button', { name: 'Создать аккаунт' }))

    expect(submitAuth).not.toHaveBeenCalled()
    expect(screen.getByRole('textbox', { name: 'Электронная почта' })).toHaveFocus()
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
    expect(screen.getByRole('textbox', { name: 'Электронная почта' })).toHaveValue(
      'anna@example.com',
    )
    expect(screen.getByLabelText('Пароль')).toHaveValue('')
    expect(screen.getByLabelText('Пароль')).toHaveAttribute('autocomplete', 'new-password')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    await user.type(screen.getByLabelText('Пароль'), 'register-password')
    await user.click(screen.getByRole('link', { name: 'Уже есть аккаунт? Войти' }))

    expect(router.state.location.pathname).toBe('/login')
    expect(screen.getByRole('textbox', { name: 'Электронная почта' })).toHaveValue(
      'anna@example.com',
    )
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

    expect(screen.getByRole('textbox', { name: 'Электронная почта' })).toBeDisabled()
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
    expect(screen.getByLabelText('Пароль')).toHaveValue('Testpass123')
    expect(screen.getByRole('textbox', { name: 'Электронная почта' })).toHaveValue(
      'anna@example.com',
    )
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
    expect(screen.getByRole('textbox', { name: 'Электронная почта' })).toHaveFocus()
    expect(screen.getByRole('textbox', { name: 'Электронная почта' })).not.toBeDisabled()
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

    expect(await screen.findByRole('heading', { name: 'Подтвердите почту' })).toBeInTheDocument()
    expect(screen.getByText(/Отправили ссылку на new@example.com/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Отправить письмо ещё раз' })).toBeDisabled()
    expect(useSessionStore.getState().accessToken).toBeNull()
    await waitFor(
      () => expect(screen.getByRole('button', { name: 'Отправить письмо ещё раз' })).toBeEnabled(),
      { timeout: 1500 },
    )
    await user.click(screen.getByRole('button', { name: 'Отправить письмо ещё раз' }))
    expect(resendConfirmation).toHaveBeenCalledWith('new@example.com', expect.any(AbortSignal))
    expect(screen.getByRole('button', { name: 'Отправить письмо ещё раз' })).toBeDisabled()
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

  it('keeps unavailable providers informational and opens real password recovery', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByRole('button', { name: 'Продолжить с Google' }))
    expect(screen.getByRole('status')).toHaveTextContent('пока недоступен')
    await user.click(screen.getByRole('button', { name: 'Забыли пароль?' }))
    expect(screen.getByRole('dialog', { name: 'Восстановить пароль' })).toBeVisible()
    expect(submitAuth).not.toHaveBeenCalled()
    expect(useSessionStore.getState().accessToken).toBeNull()
  })
})
