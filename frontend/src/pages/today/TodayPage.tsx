import { Outlet, useLocation, useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { Button } from '@/shared/ui/button/Button'
import { CheckIcon, PlusIcon, XIcon } from '@/shared/ui/icon/icons'
import { PageHeader } from '@/shared/ui/page-header/PageHeader'
import { useSessionStore } from '@/stores/session'
import type { Task } from '@/shared/model/task'
import styles from './TodayPage.module.css'

export function TodayPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const generation = useSessionStore((state) => state.generation)
  const created = (location.state as { taskCreated?: { task: Task; generation: number } } | null)
    ?.taskCreated

  return (
    <>
      <title>Сегодня · Идеальный день</title>
      <PageHeader title="Сегодня" description="Энергетический профиль и план на день.">
        <Button data-new-task-trigger onClick={() => navigate(paths.newTask)}>
          <PlusIcon />
          Добавить задачу
        </Button>
      </PageHeader>
      {created?.generation === generation ? (
        <div className={styles.notice} role="status">
          <CheckIcon size={18} />
          <div>
            <p className="text-label">Задача добавлена</p>
            <p className="text-caption">
              {created.task.title} · {created.task.planned_date.split('-').reverse().join('.')}
            </p>
            {created.task.status === 'pending' ? (
              <p className="text-caption">Пока не размещена в расписании.</p>
            ) : null}
          </div>
          <Button
            variant="ghost"
            size="s"
            aria-label="Закрыть уведомление"
            onClick={() => navigate(location.pathname, { replace: true, state: null })}
          >
            <XIcon size={16} />
          </Button>
        </div>
      ) : null}
      <Outlet />
    </>
  )
}
