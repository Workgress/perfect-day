import { useThemeStore } from './theme'

describe('theme store', () => {
  it('uses system mode by default', () => {
    expect(useThemeStore.getState().mode).toBe('system')
  })

  it.each(['light', 'dark', 'system'] as const)('restores a saved %s preference', async (mode) => {
    localStorage.setItem('pd-theme', JSON.stringify({ state: { mode }, version: 1 }))
    await useThemeStore.persist.rehydrate()
    expect(useThemeStore.getState().mode).toBe(mode)
  })

  it('uses system mode for an invalid saved preference', async () => {
    localStorage.setItem('pd-theme', JSON.stringify({ state: { mode: 'sepia' }, version: 1 }))
    await useThemeStore.persist.rehydrate()
    expect(useThemeStore.getState().mode).toBe('system')
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
