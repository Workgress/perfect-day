import { requestLogout, requestTokens } from '@/shared/api/auth'
import { HttpError } from '@/shared/api/http'
import { useSessionStore } from '@/stores/session'

let refreshing: Promise<string | null> | null = null
let channel: BroadcastChannel | null = null

export function expireSession() {
  useSessionStore.getState().signOut()
}

export function refreshAccessToken(): Promise<string | null> {
  if (refreshing) return refreshing
  const generation = useSessionStore.getState().generation
  refreshing = requestTokens('/auth/refresh')
    .then((token) => {
      if (useSessionStore.getState().generation !== generation) return null
      useSessionStore.getState().setAccessToken(token.access_token, token.expires_in)
      return token.access_token
    })
    .catch((error: unknown) => {
      if (error instanceof HttpError && error.status === 401) return null
      throw error
    })
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

export async function restoreSession() {
  if (useSessionStore.getState().status !== 'restoring') return true
  const token = await refreshAccessToken()
  if (!token && useSessionStore.getState().status === 'restoring') expireSession()
  return true
}

export async function logoutSession() {
  await requestLogout()
  expireSession()
  channel?.postMessage('logout')
}

export function startSessionSync() {
  if (!('BroadcastChannel' in window)) return () => {}
  channel = new BroadcastChannel('pd-session-events')
  const connection = channel
  connection.onmessage = (event: MessageEvent<unknown>) => {
    if (event.data === 'logout') expireSession()
    if (event.data === 'login') {
      expireSession()
      useSessionStore.setState({ status: 'restoring' })
    }
  }
  return () => {
    connection.close()
    if (channel === connection) channel = null
  }
}

export function announceLogin() {
  channel?.postMessage('login')
}
