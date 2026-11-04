import { useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { Button } from '@/shared/ui/button/Button'
import { TextField } from '@/shared/ui/form-field/FormField'
import { ArrowLeftIcon, ArrowRightIcon, ShieldCheckIcon } from '@/shared/ui/icon/icons'
import { useSessionStore } from '@/stores/session'
import { isTime, parseBirthDate } from './model'
import { OnboardingStep } from './OnboardingStep'
import styles from './OnboardingStep.module.css'

export function BirthDatePage() {
  const navigate = useNavigate()
  const draft = useSessionStore((state) => state.onboarding)
  const update = useSessionStore((state) => state.updateOnboarding)
  const updateUser = useSessionStore((state) => state.updateUser)
  const signOut = useSessionStore((state) => state.signOut)
  const [submitted, setSubmitted] = useState(false)
  const dateRef = useRef<HTMLInputElement>(null)
  const timeRef = useRef<HTMLInputElement>(null)
  const date = parseBirthDate(draft.birthDate)
  const dateError = !date
    ? 'Укажите существующую дату от 1900 года до сегодняшнего дня в формате ДД.ММ.ГГГГ.'
    : undefined
  const timeError =
    draft.birthTime && !isTime(draft.birthTime) ? 'Укажите время от 00:00 до 23:59.' : undefined

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    setSubmitted(true)
    if (!date || timeError) {
      if (!date) dateRef.current?.focus()
      else timeRef.current?.focus()
      return
    }
    updateUser({ birthDate: date, birthTime: draft.birthTime || null })
    navigate(paths.onboarding.chronotype)
  }

  return (
    <OnboardingStep
      title="Когда вы родились?"
      description="От даты рождения считаются три цикла: физический (23 дня), эмоциональный (28) и интеллектуальный (33)."
    >
      <form className={styles.form} noValidate onSubmit={handleSubmit} aria-label="Дата рождения">
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
            Данные пока сохраняются только в этом браузере. Предпросмотр справа — пример профиля.
          </span>
        </p>
        <div className={styles.actions}>
          <Button
            variant="ghost"
            onClick={() => {
              signOut()
              navigate(paths.login)
            }}
          >
            <ArrowLeftIcon />
            Назад
          </Button>
          <Button type="submit">
            <ArrowRightIcon />
            Дальше
          </Button>
        </div>
      </form>
    </OnboardingStep>
  )
}
