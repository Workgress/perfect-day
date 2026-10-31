import { useThemeStore } from '@/stores/theme'
import { Button } from '@/shared/ui/button/Button'
import { MoonIcon, SunIcon } from '@/shared/ui/icon/icons'
import { useResolvedTheme } from './useResolvedTheme'

export function ThemeToggle() {
  const theme = useResolvedTheme()
  const setMode = useThemeStore((state) => state.setMode)
  const next = theme === 'dark' ? 'light' : 'dark'

  return (
    <Button
      variant="ghost"
      size="s"
      aria-label={next === 'light' ? 'Включить светлую тему' : 'Включить тёмную тему'}
      onClick={() => setMode(next)}
    >
      {next === 'light' ? <SunIcon /> : <MoonIcon />}
    </Button>
  )
}
