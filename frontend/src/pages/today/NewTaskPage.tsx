import { useEffect, useId } from 'react'
import { useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { Button } from '@/shared/ui/button/Button'
import { XIcon } from '@/shared/ui/icon/icons'
import styles from './NewTaskPage.module.css'

export function NewTaskPage() {
  const navigate = useNavigate()
  const titleId = useId()

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') navigate(paths.today)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [navigate])

  return (
    <div className={styles.scrim}>
      <title>Новая задача · Идеальный день</title>
      <section role="dialog" aria-modal="true" aria-labelledby={titleId} className={styles.panel}>
        <header className={styles.header}>
          <h2 id={titleId} className="text-heading">
            Новая задача
          </h2>
          <Button
            variant="ghost"
            size="s"
            aria-label="Закрыть"
            onClick={() => navigate(paths.today)}
          >
            <XIcon />
          </Button>
        </header>
        <p className={`text-body-s ${styles.description}`}>
          Название, длительность, тип и приоритет — алгоритм подберёт лучшее время.
        </p>
      </section>
    </div>
  )
}
