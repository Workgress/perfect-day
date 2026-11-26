import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { useMutation } from '@tanstack/react-query'
import { Button } from '@/shared/ui/button/Button'
import { FormMessage, TextField } from '@/shared/ui/form-field/FormField'
import { useTaskDialog } from '@/pages/today/useTaskDialog'
import { AuthError, requestPasswordRecovery, validateCredentials } from './auth'
import { cooldownLabel, useAuthCooldown } from './useAuthCooldown'
import styles from './RecoveryDialog.module.css'

export function RecoveryDialog({
  initialEmail = '',
  onClose,
}: {
  initialEmail?: string
  onClose: () => void
}) {
  const id = useId()
  const [email, setEmail] = useState(initialEmail)
  const [sent, setSent] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState('')
  const [fieldError, setFieldError] = useState('')
  const request = useRef<AbortController | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const cooldown = useAuthCooldown()
  const mutation = useMutation({
    mutationFn: ({ address, signal }: { address: string; signal: AbortSignal }) =>
      requestPasswordRecovery(address, signal),
    retry: false,
    gcTime: 0,
  })
  const close = () => {
    if (!request.current) onClose()
  }
  const { dialogRef, onKeyDown } = useTaskDialog(
    close,
    '[data-recovery-trigger]',
    '[name="recoveryEmail"]',
  )
  useEffect(() => () => request.current?.abort(), [])
  useEffect(() => {
    if (sent) heading.current?.focus()
  }, [sent])
  useEffect(() => {
    if (fieldError && !mutation.isPending)
      dialogRef.current?.querySelector<HTMLInputElement>('input')?.focus()
  }, [fieldError, mutation.isPending, dialogRef])
  const emailError =
    fieldError ||
    (submitted ? validateCredentials({ email, password: 'unused' }, 'login').email : undefined)
  const send = async (event?: FormEvent) => {
    event?.preventDefault()
    event?.stopPropagation()
    if (request.current || cooldown.seconds) return
    setSubmitted(true)
    setError('')
    setFieldError('')
    if (validateCredentials({ email, password: 'unused' }, 'login').email) {
      dialogRef.current?.querySelector<HTMLInputElement>('input')?.focus()
      return
    }
    const controller = new AbortController()
    request.current = controller
    try {
      await mutation.mutateAsync({ address: email.trim(), signal: controller.signal })
      if (controller.signal.aborted) return
      setSent(true)
      cooldown.start(60)
    } catch (reason) {
      if (controller.signal.aborted) return
      setError(
        reason instanceof Error
          ? reason.message
          : 'Не удалось отправить письмо. Повторите попытку.',
      )
      if (reason instanceof AuthError) {
        setFieldError(reason.fields.email ?? '')
        if (reason.retryAfter || reason.code === 'RATE_LIMIT_EXCEEDED')
          cooldown.start(reason.retryAfter || 60)
      }
    } finally {
      if (request.current === controller) request.current = null
      mutation.reset()
    }
  }
  return createPortal(
    <dialog
      ref={dialogRef}
      className={styles.dialog}
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-description`}
      aria-busy={mutation.isPending}
      onCancel={(event) => {
        event.preventDefault()
        event.stopPropagation()
        close()
      }}
      onKeyDown={(event) => {
        event.stopPropagation()
        if (event.key === 'Escape') {
          event.preventDefault()
          close()
        } else onKeyDown(event)
      }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return
        const box = event.currentTarget.getBoundingClientRect()
        if (
          event.clientX < box.left ||
          event.clientX > box.right ||
          event.clientY < box.top ||
          event.clientY > box.bottom
        )
          close()
      }}
    >
      <div className={styles.content}>
        <div className={styles.closeRow}>
          <button
            type="button"
            className={styles.close}
            disabled={mutation.isPending}
            onClick={close}
          >
            Закрыть
          </button>
        </div>
        <div className={styles.intro}>
          <h2 id={`${id}-title`} ref={heading} tabIndex={-1}>
            {sent ? 'Проверьте почту' : 'Восстановить пароль'}
          </h2>
          <p id={`${id}-description`}>
            {sent ? (
              <>
                Если аккаунт с адресом <strong>{email.trim()}</strong> существует, вы получите
                письмо со ссылкой для сброса пароля.
              </>
            ) : (
              'Укажите почту аккаунта. Отправим ссылку для создания нового пароля.'
            )}
          </p>
        </div>
        {error ? <FormMessage>{error}</FormMessage> : null}
        {sent ? (
          <>
            <Button onClick={close} disabled={mutation.isPending}>
              Понятно
            </Button>
            <Button
              variant="secondary"
              disabled={mutation.isPending || cooldown.seconds > 0}
              onClick={() => void send()}
            >
              {mutation.isPending
                ? 'Отправляем…'
                : cooldown.seconds
                  ? `Повторить через ${cooldownLabel(cooldown.seconds)}`
                  : 'Отправить письмо ещё раз'}
            </Button>
          </>
        ) : (
          <form className={styles.form} onSubmit={send} noValidate>
            <TextField
              label="Электронная почта"
              name="recoveryEmail"
              type="email"
              autoComplete="email"
              autoCapitalize="none"
              spellCheck={false}
              required
              disabled={mutation.isPending}
              value={email}
              error={emailError}
              onChange={(event) => {
                setEmail(event.target.value)
                setFieldError('')
              }}
            />
            <Button type="submit" disabled={mutation.isPending || cooldown.seconds > 0}>
              {mutation.isPending
                ? 'Отправляем…'
                : cooldown.seconds
                  ? `Повторить через ${cooldownLabel(cooldown.seconds)}`
                  : 'Отправить ссылку'}
            </Button>
            <Button variant="ghost" disabled={mutation.isPending} onClick={close}>
              Отмена
            </Button>
          </form>
        )}
      </div>
    </dialog>,
    document.body,
  )
}
