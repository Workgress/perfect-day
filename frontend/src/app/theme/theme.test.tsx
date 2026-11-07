import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import indexHtml from '../../../index.html?raw'
import { useThemeStore } from '@/stores/theme'
import { mockMatchMedia } from '@/test/matchMedia'
import { isThemeMode, resolveTheme, THEME_COLORS } from './theme'
import { ThemeSwitcher } from './ThemeSwitcher'
import { ThemeSync } from './ThemeSync'
import { ThemeToggle } from './ThemeToggle'

function addThemeColorMeta() {
  const meta = document.createElement('meta')
  meta.name = 'theme-color'
  meta.content = ''
  document.head.append(meta)
  return meta
}

function currentTheme() {
  return document.documentElement.dataset.theme
}

describe('resolveTheme', () => {
  it('keeps explicit modes', () => {
    expect(resolveTheme('light', true)).toBe('light')
    expect(resolveTheme('dark', false)).toBe('dark')
  })

  it('follows the system in system mode', () => {
    expect(resolveTheme('system', true)).toBe('dark')
    expect(resolveTheme('system', false)).toBe('light')
  })

  it('recognizes theme modes', () => {
    expect(isThemeMode('system')).toBe(true)
    expect(isThemeMode('sepia')).toBe(false)
  })
})

describe('ThemeSync', () => {
  let meta: HTMLMetaElement

  beforeEach(() => {
    meta = addThemeColorMeta()
  })

  afterEach(() => {
    meta.remove()
  })

  it('applies the dark system preference by default', () => {
    render(<ThemeSync />)
    expect(currentTheme()).toBe('dark')
    expect(meta.content).toBe(THEME_COLORS.dark)
  })

  it('applies the light system preference by default', () => {
    mockMatchMedia(false)
    render(<ThemeSync />)
    expect(currentTheme()).toBe('light')
    expect(meta.content).toBe(THEME_COLORS.light)
  })

  it('applies the selected mode', () => {
    useThemeStore.setState({ mode: 'light' })
    render(<ThemeSync />)
    expect(currentTheme()).toBe('light')
    expect(meta.content).toBe(THEME_COLORS.light)
  })

  it('follows system changes without requiring a selection in settings', () => {
    const media = mockMatchMedia(true)
    render(<ThemeSync />)
    expect(currentTheme()).toBe('dark')

    act(() => media.setPrefersDark(false))
    expect(currentTheme()).toBe('light')
  })

  it('ignores system changes in explicit mode', () => {
    const media = mockMatchMedia(true)
    useThemeStore.setState({ mode: 'dark' })
    render(<ThemeSync />)

    act(() => media.setPrefersDark(false))
    expect(currentTheme()).toBe('dark')
  })
})

describe('ThemeSwitcher', () => {
  it('switches and persists the mode', async () => {
    render(
      <>
        <ThemeSync />
        <ThemeSwitcher />
      </>,
    )
    expect(screen.getByRole('radio', { name: 'Как в системе' })).toHaveAttribute(
      'aria-checked',
      'true',
    )

    await userEvent.click(screen.getByRole('radio', { name: 'Светлая' }))

    expect(screen.getByRole('radio', { name: 'Светлая' })).toHaveAttribute('aria-checked', 'true')
    expect(currentTheme()).toBe('light')
    expect(JSON.parse(localStorage.getItem('pd-theme') ?? 'null').state.mode).toBe('light')
  })

  it('selects system mode', async () => {
    mockMatchMedia(false)
    render(
      <>
        <ThemeSync />
        <ThemeSwitcher />
      </>,
    )
    await userEvent.click(screen.getByRole('radio', { name: 'Как в системе' }))
    expect(useThemeStore.getState().mode).toBe('system')
    expect(currentTheme()).toBe('light')
  })
})

describe('ThemeToggle', () => {
  it('toggles between dark and light', async () => {
    render(
      <>
        <ThemeSync />
        <ThemeToggle />
      </>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Включить светлую тему' }))
    expect(currentTheme()).toBe('light')

    await userEvent.click(screen.getByRole('button', { name: 'Включить тёмную тему' }))
    expect(currentTheme()).toBe('dark')
  })

  it('switches system mode to the opposite explicit theme', async () => {
    mockMatchMedia(false)
    useThemeStore.setState({ mode: 'system' })
    render(<ThemeToggle />)
    await userEvent.click(screen.getByRole('button', { name: 'Включить тёмную тему' }))
    expect(useThemeStore.getState().mode).toBe('dark')
  })
})

describe('inline theme script', () => {
  const script = /<script>([\s\S]*?)<\/script>/.exec(indexHtml)?.[1] ?? ''
  let meta: HTMLMetaElement

  function runScript() {
    new Function(script)()
  }

  beforeEach(() => {
    meta = addThemeColorMeta()
  })

  afterEach(() => {
    meta.remove()
  })

  it('exists in index.html', () => {
    expect(script).toContain('pd-theme')
  })

  it.each([true, false])(
    'follows the system before React starts when prefersDark is %s',
    (prefersDark) => {
      mockMatchMedia(prefersDark)
      runScript()
      expect(currentTheme()).toBe(prefersDark ? 'dark' : 'light')
      expect(meta.content).toBe(prefersDark ? THEME_COLORS.dark : THEME_COLORS.light)
    },
  )

  it('reads the mode saved by the theme store', () => {
    useThemeStore.getState().setMode('light')
    runScript()
    expect(currentTheme()).toBe('light')
    expect(meta.content).toBe(THEME_COLORS.light)
  })

  it('resolves system mode before React starts', () => {
    mockMatchMedia(false)
    useThemeStore.getState().setMode('system')
    runScript()
    expect(currentTheme()).toBe('light')
  })

  it('follows the system on broken storage', () => {
    mockMatchMedia(false)
    localStorage.setItem('pd-theme', '{broken')
    runScript()
    expect(currentTheme()).toBe('light')
  })
})
