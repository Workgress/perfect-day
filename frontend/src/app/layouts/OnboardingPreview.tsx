import { PreviewCard } from '@/shared/ui/onboarding/PreviewCard'
import styles from './OnboardingPreview.module.css'

const CYCLES = [
  {
    type: 'physical',
    label: 'Физический · 23 дня',
    value: '+94 %',
    phase: 'Пик',
    hint: 'Спорт — в окне 15–16',
  },
  {
    type: 'emotional',
    label: 'Эмоциональный · 28 дней',
    value: '−62 %',
    phase: 'Минимум',
    hint: 'Без встреч, рутина после 16:00',
  },
  {
    type: 'intellectual',
    label: 'Интеллектуальный · 33 дня',
    value: '+95 %',
    phase: 'Пик',
    hint: 'Сложная учёба — 10–12',
  },
] as const

export function OnboardingPreview({ profile = false }: { profile?: boolean }) {
  return (
    <PreviewCard
      eyebrow={profile ? undefined : 'Что вы получите'}
      title={profile ? 'Ваш профиль на сегодня' : 'Энергетический профиль на каждый день'}
      footer={
        profile
          ? 'Пример профиля. Значения пока не зависят от введённых данных.'
          : 'Пример профиля. Ваш появится сразу после ввода даты рождения.'
      }
    >
      {profile ? (
        <p className={`text-caption ${styles.hint}`}>Пример значений трёх циклов</p>
      ) : null}
      {CYCLES.map((cycle) => (
        <div key={cycle.type} className={styles.cycle} data-cycle={cycle.type}>
          <p className={`text-label-s ${styles.label}`}>
            <span className={styles.swatch} aria-hidden="true" />
            {cycle.label}
          </p>
          <p className={styles.value}>
            <span className="text-number-l">{cycle.value}</span>
            <span className="text-label">{cycle.phase}</span>
          </p>
          <p className={`text-caption ${styles.hint}`}>{cycle.hint}</p>
        </div>
      ))}
    </PreviewCard>
  )
}
