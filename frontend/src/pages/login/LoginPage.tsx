import { useLocation, useNavigate } from 'react-router'
import type { RedirectState } from '@/app/router/guards'
import { paths } from '@/app/router/paths'
import { useSession } from '@/app/session/SessionContext'
import { Button } from '@/shared/ui/button/Button'
import { ArrowRightIcon } from '@/shared/ui/icon/icons'
import styles from './LoginPage.module.css'

export function LoginPage() {
  const { signIn } = useSession().actions
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as RedirectState | null)?.from ?? paths.today

  const handleSignIn = () => {
    signIn('Анна')
    navigate(from, { replace: true })
  }

  return (
    <main className={styles.page}>
      <title>Вход · Идеальный день</title>
      <div className={styles.card}>
        <h1 className="text-title">Идеальный день</h1>
        <p className={`text-body-s ${styles.description}`}>
          Планировщик, который раскладывает задачи по вашим биоритмам и хронотипу.
        </p>
        <Button onClick={handleSignIn}>
          Войти
          <ArrowRightIcon />
        </Button>
      </div>
    </main>
  )
}
