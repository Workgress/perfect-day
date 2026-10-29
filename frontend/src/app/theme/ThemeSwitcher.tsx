import { useThemeStore } from '@/stores/theme'
import * as Segment from '@/shared/ui/segment/Segment'
import { isThemeMode } from './theme'

export function ThemeSwitcher() {
  const mode = useThemeStore((state) => state.mode)
  const setMode = useThemeStore((state) => state.setMode)

  return (
    <Segment.Root
      value={mode}
      onValueChange={(value) => {
        if (isThemeMode(value)) setMode(value)
      }}
      aria-label="Тема оформления"
    >
      <Segment.Item value="light">Светлая</Segment.Item>
      <Segment.Item value="dark">Тёмная</Segment.Item>
      <Segment.Item value="system">Как в системе</Segment.Item>
    </Segment.Root>
  )
}
