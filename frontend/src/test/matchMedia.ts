import { vi } from 'vitest'

export function mockMatchMedia(initialPrefersDark: boolean) {
  let prefersDark = initialPrefersDark
  const listeners = new Set<() => void>()

  vi.stubGlobal(
    'matchMedia',
    vi.fn((media: string) => ({
      media,
      get matches() {
        return media.includes('dark') ? prefersDark : !prefersDark
      },
      onchange: null,
      addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => true,
    })),
  )

  return {
    setPrefersDark(next: boolean) {
      prefersDark = next
      for (const listener of listeners) listener()
    },
  }
}
