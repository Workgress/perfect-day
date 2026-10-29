import { useSyncExternalStore } from 'react'
import { useThemeStore } from '@/stores/theme'
import { resolveTheme } from './theme'

const DARK_QUERY = '(prefers-color-scheme: dark)'

function subscribe(onChange: () => void) {
  const query = window.matchMedia(DARK_QUERY)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

function getPrefersDark() {
  return window.matchMedia(DARK_QUERY).matches
}

export function useSystemPrefersDark() {
  return useSyncExternalStore(subscribe, getPrefersDark, () => true)
}

export function useResolvedTheme() {
  const mode = useThemeStore((state) => state.mode)
  const prefersDark = useSystemPrefersDark()
  return resolveTheme(mode, prefersDark)
}
