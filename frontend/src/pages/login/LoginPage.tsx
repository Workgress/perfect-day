import { useLocation, useNavigate } from 'react-router'
import type { RedirectState } from '@/app/router/guards'
import { paths } from '@/app/router/paths'
import { Button } from '@/shared/ui/button/Button'
import { ArrowRightIcon } from '@/shared/ui/icon/icons'
import { useSessionStore } from '@/stores/session'
import styles from './LoginPage.module.css'

const DEMO_SESSION = {
  accessToken: 'demo-token',
  user: { name: 'Анна', birthDate: null, chronotype: null },
}

export function LoginPage() {
  const signIn = useSessionStore((state) => state.signIn)
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as RedirectState | null)?.from ?? paths.today

  const handleSignIn = () => {
    signIn(DEMO_SESSION)
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
