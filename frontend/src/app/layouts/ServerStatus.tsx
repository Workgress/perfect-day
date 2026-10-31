import { useQuery } from '@tanstack/react-query'
import { healthQuery } from '@/shared/api/health'
import styles from './ServerStatus.module.css'

const LABELS = {
  pending: 'Проверяем связь…',
  success: 'Сервер доступен',
  error: 'Нет связи с сервером',
} as const

export function ServerStatus() {
  const { status } = useQuery(healthQuery)

  return (
    <p className={`text-caption ${styles.status}`} data-status={status} role="status">
      <span className={styles.dot} aria-hidden="true" />
      {LABELS[status]}
    </p>
  )
}
