import { isRouteErrorResponse, useRouteError } from 'react-router'
import { Button } from '@/shared/ui/button/Button'
import { RefreshIcon } from '@/shared/ui/icon/icons'
import styles from './ErrorScreen.module.css'

export function RouteErrorPage() {
  const error = useRouteError()
  const status = isRouteErrorResponse(error) ? error.status : null

  return (
    <main className={styles.page}>
      <title>Ошибка · Идеальный день</title>
      {status ? <p className={`text-number-l ${styles.code}`}>{status}</p> : null}
      <h1 className="text-title">Что-то пошло не так</h1>
      <p className={`text-body-s ${styles.description}`}>
        Попробуйте обновить страницу. Если ошибка повторится, напишите нам.
      </p>
      <Button variant="secondary" onClick={() => window.location.reload()}>
        <RefreshIcon />
        Обновить
      </Button>
    </main>
  )
}
