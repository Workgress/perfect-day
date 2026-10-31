import { useThemeStore } from './theme'

describe('theme store', () => {
  it('uses dark mode by default', () => {
    expect(useThemeStore.getState().mode).toBe('dark')
  })

  it('changes and persists the mode', () => {
    useThemeStore.getState().setMode('system')
    expect(useThemeStore.getState().mode).toBe('system')
    expect(JSON.parse(localStorage.getItem('pd-theme') ?? 'null')).toEqual({
      state: { mode: 'system' },
      version: 1,
    })
  })
})
