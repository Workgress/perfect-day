import { useState } from 'react'
import { localDateTime, resolveLocalDateTime } from '@/shared/lib/dateTime'
import { Button } from '@/shared/ui/button/Button'
import { TextField } from '@/shared/ui/form-field/FormField'
import styles from './TaskDetailsPanel.module.css'

export function TaskPlacementForm({
  date,
  start,
  timezone,
  busy,
  disabled,
  onSave,
  onCancel,
  submitLabel = 'Сохранить время',
  cancelLabel = 'Отмена',
  hint,
}: {
  date: string
  start?: string | null
  timezone: string
  busy: boolean
  disabled: boolean
  onSave: (date: string, start: string) => Promise<boolean>
  onCancel: () => void
  submitLabel?: string
  cancelLabel?: string
  hint?: string
}) {
  const [value, setValue] = useState(start ? localDateTime(new Date(start), timezone) : `${date}T`)
  const [error, setError] = useState('')
  return (
    <form
      className={styles.placementForm}
      aria-label="Выбор времени задачи"
      noValidate
      onSubmit={async (event) => {
        event.preventDefault()
        if (busy || disabled) return
        const resolved = resolveLocalDateTime(value, timezone)
        if (resolved.status !== 'valid') {
          setError(
            resolved.status === 'ambiguous'
              ? 'Это время встречается дважды при переводе часов. Выберите другое.'
              : resolved.status === 'nonexistent'
                ? 'Такого времени нет из-за перевода часов. Выберите другое.'
                : 'Укажите дату и время начала задачи.',
          )
          return
        }
        setError('')
        await onSave(value.slice(0, 10), new Date(resolved.instant).toISOString())
      }}
    >
      <TextField
        label="Начало задачи"
        type="datetime-local"
        required
        autoFocus
        value={value}
        disabled={busy}
        error={error}
        hint={hint ?? `Часовой пояс: ${timezone}. После переноса время будет закреплено.`}
        onChange={(event) => {
          setValue(event.target.value)
          setError('')
        }}
      />
      <div className={styles.placementButtons}>
        <Button type="submit" disabled={busy || disabled}>
          {busy ? 'Сохраняем…' : submitLabel}
        </Button>
        <Button variant="ghost" disabled={busy} onClick={onCancel}>
          {cancelLabel}
        </Button>
      </div>
    </form>
  )
}
