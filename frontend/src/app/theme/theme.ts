import type { ThemeMode } from '@/stores/theme'

export type ResolvedTheme = 'light' | 'dark'

export const THEME_COLORS: Record<ResolvedTheme, string> = {
  dark: '#0e0e11',
  light: '#f6f5f1',
}

const THEME_MODES = new Set<string>(['light', 'dark', 'system'])

export function isThemeMode(value: string): value is ThemeMode {
  return THEME_MODES.has(value)
}

export function resolveTheme(mode: ThemeMode, prefersDark: boolean): ResolvedTheme {
  if (mode === 'system') return prefersDark ? 'dark' : 'light'
  return mode
}

export function applyTheme(theme: ResolvedTheme) {
  const root = document.documentElement
  root.dataset.theme = theme
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLORS[theme])
}
