import { useRef, useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { Button } from '@/shared/ui/button/Button'
import { FormMessage, TextField } from '@/shared/ui/form-field/FormField'
import { apiError } from '@/shared/api/errors'
import { LogoutButton } from '@/app/LogoutButton'
import { useSaveProfile } from './api'
import { ArrowRightIcon, ShieldCheckIcon } from '@/shared/ui/icon/icons'
import { useSessionStore } from '@/stores/session'
import { isTime, parseBirthDate } from './model'
import { OnboardingStep } from './OnboardingStep'
import styles from './OnboardingStep.module.css'

export function BirthDatePage() {
  const navigate = useNavigate()
  const draft = useSessionStore((state) => state.onboarding)
  const update = useSessionStore((state) => state.updateOnboarding)
  const isLocalProfile = useSessionStore((state) => state.isLocalProfile)
  const location = useLocation()
  const { save } = useSaveProfile()
  const [submitted, setSubmitted] = useState(false)
  const dateRef = useRef<HTMLInputElement>(null)
  const timeRef = useRef<HTMLInputElement>(null)
  const date = parseBirthDate(draft.birthDate)
  const dateError = !date
    ? 'Укажите существующую дату от 1900 года до сегодняшнего дня в формате ДД.ММ.ГГГГ.'
    : undefined
  const timeError =
    draft.birthTime && !isTime(draft.birthTime) ? 'Укажите время от 00:00 до 23:59.' : undefined

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitted(true)
    if (!date || timeError || save.isPending) {
      if (!date) dateRef.current?.focus()
      else timeRef.current?.focus()
      return
    }
    try {
      await save.mutateAsync({
        birth_date: date,
        birth_time: draft.birthTime ? `${draft.birthTime}:00` : null,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      })
      navigate(paths.onboarding.chronotype, { state: location.state })
    } catch {}
  }

  return (
    <OnboardingStep
      title="Когда вы родились?"
      description="От даты рождения считаются три цикла: физический (23 дня), эмоциональный (28) и интеллектуальный (33)."
    >
      <form className={styles.form} noValidate onSubmit={handleSubmit} aria-label="Дата рождения">
        {save.isError ? <FormMessage>{apiError(save.error)}</FormMessage> : null}
        <fieldset disabled={save.isPending} className={styles.formFields}>
          <TextField
            ref={dateRef}
            label="Дата рождения"
            name="birthDate"
            autoComplete="bday"
            inputMode="numeric"
            placeholder="ДД.ММ.ГГГГ"
            maxLength={10}
            required
            value={draft.birthDate}
            error={submitted ? dateError : undefined}
            onChange={(event) => update({ birthDate: event.target.value })}
          />
          <TextField
            ref={timeRef}
            label="Время рождения · необязательно"
            name="birthTime"
            inputMode="numeric"
            placeholder="Не знаю — посчитаем от 12:00"
            maxLength={5}
            value={draft.birthTime}
            error={submitted ? timeError : undefined}
            onChange={(event) => update({ birthTime: event.target.value })}
          />
          <p className={`text-caption ${styles.note}`}>
            <ShieldCheckIcon size={16} />
            <span>
              {isLocalProfile
                ? 'Пока данные сохраняются только в этом браузере.'
                : 'Данные сохраняются в профиле после нажатия «Дальше».'}{' '}
              Предпросмотр справа — пример профиля.
            </span>
          </p>
        </fieldset>
        <div className={styles.actions}>
          <LogoutButton label="Назад" />
          <Button type="submit" disabled={save.isPending}>
            <ArrowRightIcon />
            {save.isPending ? 'Сохраняем…' : 'Дальше'}
          </Button>
        </div>
      </form>
    </OnboardingStep>
  )
}
