import { configureHttp } from '@/shared/api/http'
import { useSessionStore } from '@/stores/session'

export function setupHttp() {
  configureHttp({
    getAccessToken: () => useSessionStore.getState().accessToken,
    onUnauthorized: () => useSessionStore.getState().signOut(),
  })
}
