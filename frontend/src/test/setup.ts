import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'
import { useSessionStore } from '@/stores/session'
import { useThemeStore } from '@/stores/theme'
import { mockMatchMedia } from './matchMedia'
import { setupHttp } from '@/app/setupHttp'

configure({ asyncUtilTimeout: 3000 })

beforeEach(() => {
  setupHttp()
  vi.stubGlobal('scrollTo', vi.fn())
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: URL | string) =>
      String(input).endsWith('/auth/refresh')
        ? Response.json(
            { error: { code: 'INVALID_REFRESH_TOKEN', message: 'Сессия истекла' } },
            { status: 401 },
          )
        : Response.json({ status: 'ok' }),
    ),
  )
  mockMatchMedia(true)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
  delete document.documentElement.dataset.theme
  useSessionStore.setState(useSessionStore.getInitialState(), true)
  useThemeStore.setState(useThemeStore.getInitialState(), true)
})
