import { useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { Button } from '@/shared/ui/button/Button'
import { SelectField } from '@/shared/ui/form-field/FormField'
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  ClockIcon,
  MoonIcon,
  SunIcon,
  ZapIcon,
} from '@/shared/ui/icon/icons'
import { useSessionStore } from '@/stores/session'
import { TIME_OPTIONS } from './model'
import { OnboardingStep } from './OnboardingStep'
import styles from './OnboardingStep.module.css'

const CHRONOTYPES = [
  {
    value: 'lark',
    label: 'Жаворонок',
    description: 'Бодрее утром',
    peak: '08:00–11:00',
    Icon: SunIcon,
  },
  {
    value: 'dove',
    label: 'Голубь',
    description: 'Ровный ритм',
    peak: '09:00–12:00',
    Icon: ZapIcon,
  },
  {
    value: 'owl',
    label: 'Сова',
    description: 'Лучше после обеда и вечером',
    peak: '12:00–15:00',
    Icon: MoonIcon,
  },
] as const

export function ChronotypePage() {
  const navigate = useNavigate()
  const draft = useSessionStore((state) => state.onboarding)
  const update = useSessionStore((state) => state.updateOnboarding)
  const updateUser = useSessionStore((state) => state.updateUser)
  const [submitted, setSubmitted] = useState(false)
  const endRef = useRef<HTMLSelectElement>(null)
  const error = draft.workEnd <= draft.workStart ? 'Конец дня должен быть позже начала.' : undefined

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    setSubmitted(true)
    if (error) {
      endRef.current?.focus()
      return
    }
    updateUser({
      chronotype: draft.chronotype,
      workStart: draft.workStart,
      workEnd: draft.workEnd,
      sleepTime: draft.sleepTime,
    })
    navigate(paths.onboarding.firstTasks)
  }

  return (
    <OnboardingStep
      title="Когда вам легче думается?"
      description="Хронотип сдвигает окна внутри дня: у «совы» они на 4 часа позже, чем у «жаворонка»."
    >
      <form
        className={styles.form}
        noValidate
        onSubmit={handleSubmit}
        aria-label="Хронотип и режим"
      >
        <fieldset className={styles.choices}>
          <legend className="visually-hidden">Хронотип</legend>
          {CHRONOTYPES.map(({ value, label, description, peak, Icon }) => (
            <label key={value} className={styles.choice}>
              <input
                type="radio"
                name="chronotype"
                value={value}
                checked={draft.chronotype === value}
                onChange={() => update({ chronotype: value })}
              />
              <Icon />
              <span className={styles.choiceText}>
                <span className="text-label">{label}</span>
                <span className={`text-caption ${styles.secondary}`}>{description}</span>
              </span>
              <span className={styles.badge}>Пик {peak}</span>
            </label>
          ))}
        </fieldset>
        <div className={styles.times}>
          <SelectField
            label="Начало дня"
            leadingIcon={<ClockIcon size={18} />}
            value={draft.workStart}
            onChange={(event) => update({ workStart: event.target.value })}
          >
            {TIME_OPTIONS.map((time) => (
              <option key={time}>{time}</option>
            ))}
          </SelectField>
          <SelectField
            ref={endRef}
            label="Конец дня"
            leadingIcon={<ClockIcon size={18} />}
            value={draft.workEnd}
            error={submitted ? error : undefined}
            onChange={(event) => update({ workEnd: event.target.value })}
          >
            {TIME_OPTIONS.map((time) => (
              <option key={time}>{time}</option>
            ))}
          </SelectField>
          <SelectField
            label="Отбой"
            leadingIcon={<ClockIcon size={18} />}
            value={draft.sleepTime}
            onChange={(event) => update({ sleepTime: event.target.value })}
          >
            {TIME_OPTIONS.map((time) => (
              <option key={time}>{time}</option>
            ))}
          </SelectField>
        </div>
        <div className={styles.actions}>
          <Button variant="ghost" onClick={() => navigate(paths.onboarding.birthDate)}>
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
