import { configureHttp } from '@/shared/api/http'
import { useSessionStore } from '@/stores/session'
import { expireSession, refreshAccessToken } from './session'

export function setupHttp() {
  configureHttp({
    getAccessToken: () => useSessionStore.getState().accessToken,
    onUnauthorized: expireSession,
    refreshAccessToken,
  })
}
