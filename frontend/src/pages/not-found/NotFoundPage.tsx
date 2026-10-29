import { useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import styles from '@/pages/error/ErrorScreen.module.css'
import { Button } from '@/shared/ui/button/Button'
import { ArrowLeftIcon } from '@/shared/ui/icon/icons'

export function NotFoundPage() {
  const navigate = useNavigate()

  return (
    <main className={styles.page}>
      <title>Страница не найдена · Идеальный день</title>
      <p className={`text-number-l ${styles.code}`}>404</p>
      <h1 className="text-title">Страница не найдена</h1>
      <p className={`text-body-s ${styles.description}`}>
        Возможно, ссылка устарела или в адресе опечатка.
      </p>
      <Button variant="secondary" onClick={() => navigate(paths.today)}>
        <ArrowLeftIcon />
        На главную
      </Button>
    </main>
  )
}
