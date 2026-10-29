import { useId } from 'react'
import { ThemeSwitcher } from '@/app/theme/ThemeSwitcher'
import { PageHeader } from '@/shared/ui/page-header/PageHeader'
import styles from './SettingsPage.module.css'

export function SettingsPage() {
  const appearanceId = useId()

  return (
    <>
      <title>Настройки · Идеальный день</title>
      <PageHeader
        title="Настройки"
        description="Профиль, хронотип, режим сна, уведомления и тема."
      />
      <section aria-labelledby={appearanceId} className={styles.section}>
        <h2 id={appearanceId} className="text-heading">
          Оформление
        </h2>
        <div className={styles.row}>
          <div className={styles.rowText}>
            <span className="text-label">Тема</span>
            <span className={`text-caption ${styles.hint}`}>Тёмная тема — по умолчанию</span>
          </div>
          <ThemeSwitcher />
        </div>
      </section>
    </>
  )
}
