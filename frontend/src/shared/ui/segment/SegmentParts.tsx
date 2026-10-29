import { createContext, use, useMemo, type ComponentProps, type KeyboardEvent } from 'react'
import { cx } from '@/shared/lib/cx'
import styles from './Segment.module.css'

type SegmentContextValue = {
  value: string
  select: (value: string) => void
}

const SegmentContext = createContext<SegmentContextValue | null>(null)

function useSegmentContext() {
  const context = use(SegmentContext)
  if (!context) {
    throw new Error('Segment.Item must be rendered inside Segment.Root')
  }
  return context
}

const NEXT_KEYS = new Set(['ArrowRight', 'ArrowDown'])
const PREV_KEYS = new Set(['ArrowLeft', 'ArrowUp'])

function moveFocus(event: KeyboardEvent<HTMLDivElement>) {
  const isNext = NEXT_KEYS.has(event.key)
  const isPrev = PREV_KEYS.has(event.key)
  const isHome = event.key === 'Home'
  const isEnd = event.key === 'End'
  if (!isNext && !isPrev && !isHome && !isEnd) return

  const items = Array.from(
    event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]:not(:disabled)'),
  )
  if (items.length === 0) return

  const current = items.findIndex((item) => item === document.activeElement)
  const last = items.length - 1
  let target = current
  if (isHome) target = 0
  else if (isEnd) target = last
  else if (isNext) target = current >= last ? 0 : current + 1
  else target = current <= 0 ? last : current - 1

  event.preventDefault()
  items[target].focus()
  items[target].click()
}

export type SegmentRootProps = Omit<ComponentProps<'div'>, 'role' | 'onChange'> & {
  value: string
  onValueChange: (value: string) => void
}

export function SegmentRoot({
  value,
  onValueChange,
  className,
  onKeyDown,
  children,
  ...props
}: SegmentRootProps) {
  const context = useMemo(() => ({ value, select: onValueChange }), [value, onValueChange])

  return (
    <SegmentContext value={context}>
      <div
        role="radiogroup"
        className={cx(styles.root, className)}
        onKeyDown={(event) => {
          onKeyDown?.(event)
          if (!event.defaultPrevented) moveFocus(event)
        }}
        {...props}
      >
        {children}
      </div>
    </SegmentContext>
  )
}

export type SegmentItemProps = Omit<ComponentProps<'button'>, 'value' | 'role'> & {
  value: string
}

export function SegmentItem({ value, className, onClick, ...props }: SegmentItemProps) {
  const { value: selectedValue, select } = useSegmentContext()
  const isSelected = selectedValue === value

  return (
    <button
      type="button"
      role="radio"
      aria-checked={isSelected}
      tabIndex={isSelected ? 0 : -1}
      className={cx(styles.item, className)}
      onClick={(event) => {
        onClick?.(event)
        if (!event.defaultPrevented) select(value)
      }}
      {...props}
    />
  )
}
