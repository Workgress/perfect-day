import { useId, type ComponentProps, type ReactNode } from 'react'
import { cx } from '@/shared/lib/cx'
import { ChevronDownIcon } from '@/shared/ui/icon/icons'
import styles from './FormField.module.css'

type FieldProps = {
  label: string
  hint?: string
  error?: string
  className?: string
}

function descriptionIds(id: string, hint?: string, error?: string, describedBy?: string) {
  return (
    [describedBy, hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ') ||
    undefined
  )
}

function Field({
  id,
  label,
  hint,
  error,
  className,
  children,
}: FieldProps & { id: string; children: ReactNode }) {
  return (
    <div className={cx(styles.field, className)}>
      <label htmlFor={id} className={cx('text-label-s', styles.label)}>
        {label}
      </label>
      {children}
      {hint ? (
        <p id={`${id}-hint`} className={cx('text-caption', styles.hint)}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} className={cx('text-caption', styles.error)} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}

export type TextFieldProps = Omit<ComponentProps<'input'>, 'className'> & FieldProps

export function TextField({
  label,
  hint,
  error,
  className,
  id,
  'aria-describedby': describedBy,
  'aria-invalid': invalid,
  ...props
}: TextFieldProps) {
  const generatedId = useId()
  const fieldId = id ?? generatedId

  return (
    <Field id={fieldId} label={label} hint={hint} error={error} className={className}>
      <input
        {...props}
        id={fieldId}
        className={styles.control}
        aria-describedby={descriptionIds(fieldId, hint, error, describedBy)}
        aria-invalid={error ? true : invalid}
      />
    </Field>
  )
}

export type SelectFieldProps = Omit<ComponentProps<'select'>, 'className' | 'multiple' | 'size'> &
  FieldProps & {
    leadingIcon?: ReactNode
  }

export function SelectField({
  label,
  hint,
  error,
  className,
  id,
  leadingIcon,
  children,
  'aria-describedby': describedBy,
  'aria-invalid': invalid,
  ...props
}: SelectFieldProps) {
  const generatedId = useId()
  const fieldId = id ?? generatedId

  return (
    <Field id={fieldId} label={label} hint={hint} error={error} className={className}>
      <div className={styles.selectWrapper}>
        {leadingIcon ? (
          <span className={styles.leadingIcon} aria-hidden="true">
            {leadingIcon}
          </span>
        ) : null}
        <select
          {...props}
          id={fieldId}
          className={cx(styles.control, styles.select)}
          data-leading={leadingIcon ? true : undefined}
          aria-describedby={descriptionIds(fieldId, hint, error, describedBy)}
          aria-invalid={error ? true : invalid}
        >
          {children}
        </select>
        <ChevronDownIcon size={16} className={styles.chevron} />
      </div>
    </Field>
  )
}

export function FormMessage({
  children,
  tone = 'error',
  className,
}: {
  children: ReactNode
  tone?: 'error' | 'info' | 'success'
  className?: string
}) {
  return (
    <p
      className={cx('text-caption', styles.message, className)}
      data-tone={tone}
      role={tone === 'error' ? 'alert' : 'status'}
    >
      {children}
    </p>
  )
}
