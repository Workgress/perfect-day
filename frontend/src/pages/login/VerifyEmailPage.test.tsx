import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useSessionStore } from '@/stores/session'
import { VerifyEmailPage } from './VerifyEmailPage'
import { installApiServer } from '@/test/apiServer'

describe('email verification', () => {
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
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      token: 'one-time-token',
    })
    expect(localStorage.getItem('pd-session')).not.toContain('one-time-token')
    window.history.replaceState(null, '', '/')
  })
})
