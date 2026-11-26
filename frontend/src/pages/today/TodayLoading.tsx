import { useSessionStore } from '@/stores/session'
import dashboard from './TodayDashboard.module.css'
import styles from './TodayLoading.module.css'

export function TodayLoading() {
  const user = useSessionStore((state) => state.user)
  const start = Number((user?.workStart ?? '08:00').slice(0, 2))
  const end = Number((user?.workEnd ?? '18:00').slice(0, 2))
  const hours = Array.from({ length: Math.max(1, end - start + 2) }, (_, i) => start + i)
  return (
    <section
      className={dashboard.dashboard}
      role="status"
      aria-label="Загружаем план дня"
      aria-busy="true"
    >
      <div className={styles.main}>
        <h2 className={styles.title}>План на день</h2>
        <p className={styles.subtitle}>Раскладываем задачи по окнам…</p>
        <div className={styles.timeline} aria-hidden="true">
          {hours.map((hour) => (
            <div className={styles.hour} key={hour}>
              <span>{String(hour % 24).padStart(2, '0')}:00</span>
              <i />
            </div>
          ))}
          <div className={styles.blocks}>
            <i />
            <i />
            <i />
            <i />
            <i />
          </div>
          <div
            className={styles.outside}
            style={{ top: (hours.length - 2) * 72 + 8 }}
            aria-hidden="true"
          >
            Вне рабочего окна · после {user?.workEnd?.slice(0, 5) ?? '18:00'}
          </div>
        </div>
      </div>
      <div className={styles.summary} aria-hidden="true">
        <div className={styles.next}>
          <i />
          <i />
          <i />
          <i />
          <i />
        </div>
        <div className={styles.load}>
          <i />
          <i />
        </div>
        <div className={styles.hints}>
          <i />
          <i />
          <i />
        </div>
      </div>
    </section>
  )
}

export function EnergyLoading() {
  return (
    <div
      className={styles.energy}
      role="status"
      aria-label="Загружаем энергетический профиль"
      aria-busy="true"
    >
      {[0, 1, 2].map((cycle) => (
        <div key={cycle} aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
        </div>
      ))}
    </div>
  )
}
