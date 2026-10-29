import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'
import { useSessionStore } from '@/stores/session'
import { useThemeStore } from '@/stores/theme'
import { mockMatchMedia } from './matchMedia'

beforeEach(() => {
  vi.stubGlobal('scrollTo', vi.fn())
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ status: 'ok' })),
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
