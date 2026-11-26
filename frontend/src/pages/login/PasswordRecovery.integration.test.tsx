import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useSessionStore } from '@/stores/session'
import { LoginPage } from './LoginPage'
import { EmailSentPage } from './EmailSentPage'
import { ResetPasswordPage } from './ResetPasswordPage'

function setup(
  path = '/login',
  handler: (path: string, init?: RequestInit) => Response | Promise<Response> = () =>
    Response.json({ message: 'accepted' }, { status: 202 }),
) {
  const fetchMock = vi.fn<typeof fetch>(async (input, init) =>
    handler(new URL(String(input)).pathname, init),
  )
  vi.stubGlobal('fetch', fetchMock)
  const router = createMemoryRouter(
    [
      { path: '/login', element: <LoginPage /> },
      { path: '/register', element: <LoginPage /> },
      { path: '/verify-email/sent', element: <EmailSentPage /> },
      { path: '/reset-password', element: <ResetPasswordPage /> },
    ],
    { initialEntries: [path] },
  )
  const view = renderWithProviders(<RouterProvider router={router} />)
  return { ...view, router, fetchMock }
}
const failure = (code: string, status: number, retryAfter?: string) =>
  Response.json(
    { error: { code, message: code } },
    { status, headers: retryAfter ? { 'Retry-After': retryAfter } : undefined },
  )
async function fillReset(password = 'Newpass123', confirmation = password) {
  await userEvent.type(screen.getByLabelText('Новый пароль'), password)
  await userEvent.type(screen.getByLabelText('Повторите пароль'), confirmation)
}
afterEach(() => {
  vi.useRealTimers()
  window.history.replaceState(null, '', '/')
})

describe('registration and password recovery API flows', () => {
  it('sends only supported registration fields and navigates to the sent-email page', async () => {
    const { router, fetchMock } = setup('/register')
    await userEvent.type(
      screen.getByRole('textbox', { name: 'Электронная почта' }),
      'anna@example.com',
    )
    await userEvent.type(screen.getByLabelText('Пароль'), 'Newpass123')
    await userEvent.type(screen.getByLabelText('Повторите пароль'), 'Newpass123')
    await userEvent.click(screen.getByRole('button', { name: 'Создать аккаунт' }))
    await screen.findByRole('heading', { name: 'Подтвердите почту' })
    expect(router.state.location.pathname).toBe('/verify-email/sent')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      email: 'anna@example.com',
      password: 'Newpass123',
    })
    expect(useSessionStore.getState().accessToken).toBeNull()
    expect(screen.getByRole('button', { name: 'Отправить письмо ещё раз' })).toBeDisabled()
  })

  it('prefills recovery, sends one real request, shows neutral confirmation, and restores focus', async () => {
    const { fetchMock } = setup()
    await userEvent.type(
      screen.getByRole('textbox', { name: 'Электронная почта' }),
      'anna@example.com',
    )
    const trigger = screen.getByRole('button', { name: 'Забыли пароль?' })
    await userEvent.click(trigger)
    const dialog = screen.getByRole('dialog', { name: 'Восстановить пароль' })
    expect(within(dialog).getByRole('textbox')).toHaveValue('anna@example.com')
    expect(within(dialog).getByRole('textbox')).toHaveFocus()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отправить ссылку' }))
    const sent = await screen.findByRole('dialog', { name: 'Проверьте почту' })
    expect(sent).toHaveTextContent('Если аккаунт с адресом anna@example.com существует')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/auth\/password\/forgot$/)
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      email: 'anna@example.com',
    })
    expect(within(sent).getByRole('button', { name: /Повторить через/ })).toBeDisabled()
    expect(useSessionStore.getState().accessToken).toBeNull()
    await userEvent.click(within(sent).getByRole('button', { name: 'Понятно' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('keeps recovery errors visible without pretending a letter was sent', async () => {
    const { fetchMock } = setup('/login', () => {
      throw new TypeError('Offline')
    })
    await userEvent.click(screen.getByRole('button', { name: 'Забыли пароль?' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByRole('textbox'), 'anna@example.com')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отправить ссылку' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Нет связи с сервером')
    expect(screen.queryByRole('heading', { name: 'Проверьте почту' })).not.toBeInTheDocument()
    expect(within(dialog).getByRole('textbox')).toHaveValue('anna@example.com')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('honors a server recovery cooldown and never automatically replays the POST', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-26T10:00:00Z'))
    const { fetchMock } = setup('/login', () => failure('RATE_LIMIT_EXCEEDED', 429, '2'))
    await userEvent.click(screen.getByRole('button', { name: 'Забыли пароль?' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByRole('textbox'), 'anna@example.com')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отправить ссылку' }))
    expect(
      await within(dialog).findByRole('button', { name: 'Повторить через 00:02' }),
    ).toBeDisabled()
    fireEvent.submit(dialog.querySelector('form')!)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    vi.setSystemTime(new Date('2026-11-26T10:00:03Z'))
    await waitFor(
      () => expect(within(dialog).getByRole('button', { name: 'Отправить ссылку' })).toBeEnabled(),
      { timeout: 1500 },
    )
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('aborts recovery on navigation and ignores a late response', async () => {
    let finish!: (response: Response) => void
    const { router, fetchMock } = setup(
      '/login',
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Забыли пароль?' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByRole('textbox'), 'anna@example.com')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отправить ссылку' }))
    fireEvent.submit(dialog.querySelector('form')!)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await act(async () => {
      await router.navigate('/register')
    })
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true)
    await act(async () => finish(Response.json({ message: 'accepted' }, { status: 202 })))
    expect(router.state.location.pathname).toBe('/register')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('scrubs the reset token, validates matching passwords and saves without silently signing in', async () => {
    useSessionStore.getState().signIn({ accessToken: 'old-session' })
    window.history.replaceState(null, '', '/reset-password#token=reset-secret')
    const { router, fetchMock } = setup(
      '/reset-password',
      () => new Response(null, { status: 204 }),
    )
    expect(window.location.hash).toBe('')
    expect(fetchMock).not.toHaveBeenCalled()
    await fillReset('Newpass123', 'Different123')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить и войти' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Пароли не совпадают.')
    expect(screen.getByLabelText('Повторите пароль')).toHaveFocus()
    expect(fetchMock).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Повторите пароль'), { target: { value: 'Newpass123' } })
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить и войти' }))
    await screen.findByText('Пароль обновлён. Войдите с новым паролем.')
    expect(router.state.location.pathname).toBe('/login')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      token: 'reset-secret',
      new_password: 'Newpass123',
    })
    expect(fetchMock.mock.calls[0][1]?.credentials).toBe('include')
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('Authorization')).toBeNull()
    expect(useSessionStore.getState().accessToken).toBeNull()
    expect(localStorage.getItem('pd-session')).not.toContain('reset-secret')
    expect(localStorage.getItem('pd-session')).not.toContain('Newpass123')
    expect(screen.getByLabelText('Пароль')).toHaveValue('')
  })

  it('handles expired reset links and offers a fresh recovery request', async () => {
    window.history.replaceState(null, '', '/reset-password#token=expired')
    const { fetchMock } = setup('/reset-password', () => failure('INVALID_EMAIL_TOKEN', 400))
    await fillReset()
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить и войти' }))
    await screen.findByRole('button', { name: 'Получить новую ссылку' })
    expect(screen.queryByLabelText('Новый пароль')).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: 'Получить новую ссылку' }))
    expect(screen.getByRole('dialog', { name: 'Восстановить пароль' })).toBeVisible()
  })

  it('does not submit a reset when the link has no token', async () => {
    const { fetchMock } = setup('/reset-password')
    expect(screen.getByText(/Ссылка восстановления недействительна/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Сохранить и войти' })).not.toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('aborts a pending reset and ignores its late success after navigation', async () => {
    window.history.replaceState(null, '', '/reset-password#token=reset-aborted')
    useSessionStore.getState().signIn({ accessToken: 'current-session' })
    let finish!: (response: Response) => void
    const { router, fetchMock } = setup(
      '/reset-password',
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    await fillReset()
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить и войти' }))
    fireEvent.submit(screen.getByRole('form', { name: 'Смена пароля' }))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await act(async () => {
      await router.navigate('/register')
    })
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true)
    await act(async () => finish(new Response(null, { status: 204 })))
    expect(router.state.location.pathname).toBe('/register')
    expect(useSessionStore.getState().accessToken).toBe('current-session')
  })
})
