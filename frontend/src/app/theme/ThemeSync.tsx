import { useEffect } from 'react'
import { applyTheme } from './theme'
import { useResolvedTheme } from './useResolvedTheme'

export function ThemeSync() {
  const theme = useResolvedTheme()

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  return null
}
