import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

export type ThemeMode = 'light' | 'dark' | 'system'

type ThemeStore = {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
}

export const useThemeStore = create<ThemeStore>()(
  persist(
    (set) => ({
      mode: 'system',
      setMode: (mode) => set({ mode }),
    }),
    {
      name: 'pd-theme',
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: ({ mode }) => ({ mode }),
      merge: (persisted, current) => {
        const mode = (persisted as { mode?: unknown } | null)?.mode
        return {
          ...current,
          mode: mode === 'light' || mode === 'dark' || mode === 'system' ? mode : 'system',
        }
      },
    },
  ),
)
