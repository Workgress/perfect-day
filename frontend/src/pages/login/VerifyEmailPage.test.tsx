import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router'
import { routes } from '@/app/router/routes'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useSessionStore } from '@/stores/session'
import { VerifyEmailPage } from './VerifyEmailPage'
import { installApiServer } from '@/test/apiServer'

describe('email verification', () => {
  afterEach(() => window.history.replaceState(null, '', '/'))

  it('keeps the success screen visible and loads onboarding only after continuing', async () => {
    window.history.replaceState(null, '', '/verify-email#token=confirmation-flow')
    const fetchMock = installApiServer()
    const router = createMemoryRouter(routes, { initialEntries: ['/verify-email'] })
    renderWithProviders(<RouterProvider router={router} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Подтвердить почту' }))
    expect(await screen.findByRole('heading', { name: 'Почта подтверждена' })).toHaveFocus()
    expect(router.state.location.pathname).toBe('/verify-email')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: 'Продолжить настройку' }))
    expect(await screen.findByRole('heading', { name: 'Когда вы родились?' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/onboarding/birth-date')
  })
  it('clears the fragment without consuming the token until explicit confirmation', async () => {
    window.history.replaceState(null, '', '/verify-email#token=one-time-token')
    const fetchMock = installApiServer()
    renderWithProviders(
      <MemoryRouter>
        <VerifyEmailPage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(window.location.hash).toBe(''))
    expect(fetchMock).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Подтвердить почту' }))
    await waitFor(() => expect(useSessionStore.getState().accessToken).toBe('real-test-token'))
    expect(screen.getByRole('heading', { name: 'Почта подтверждена' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Продолжить настройку' })).toBeEnabled()
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      token: 'one-time-token',
    })
    expect(localStorage.getItem('pd-session')).not.toContain('one-time-token')
    window.history.replaceState(null, '', '/')
  })
})
