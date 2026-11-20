import { useEffect, useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router'
import { paths, taskPath } from '@/app/router/paths'
import { Button } from '@/shared/ui/button/Button'
import { CheckIcon, PlusIcon, RefreshIcon, SearchIcon, XIcon } from '@/shared/ui/icon/icons'
import { localDate } from '@/shared/lib/dateTime'
import { useCurrentTime } from '@/shared/lib/useCurrentTime'
import { useSessionStore } from '@/stores/session'
import type { Task } from '@/shared/model/task'
import styles from './TodayPage.module.css'
import { TodayTimeline } from './TodayTimeline'
import { TodayCriticalDays } from './TodayCriticalDays'
import { TodayEnergyProfile } from './TodayEnergyProfile'
import { todayDateLabel, todayGreeting } from './todayHeaderModel'

export function TodayPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const generation = useSessionStore((state) => state.generation)
  const timezone = useSessionStore((state) => state.timezone)
  const name = useSessionStore((state) => state.user?.name)
  const now = useCurrentTime()
  const date = localDate(now, timezone)
  const [searchState, setSearchState] = useState({ generation, date, value: '' })
  const search =
    searchState.generation === generation && searchState.date === date ? searchState.value : ''
  const setSearch = (value: string) => setSearchState({ generation, date, value })
  const searchInput = useRef<HTMLInputElement>(null)
  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        searchInput.current?.focus()
      }
    }
    window.addEventListener('keydown', focusSearch)
    return () => window.removeEventListener('keydown', focusSearch)
  }, [])
  const created = (
    location.state as {
      taskCreated?: { task: Task; generation: number; requestedDate?: string }
    } | null
  )?.taskCreated
  const notice = (location.state as { taskNotice?: { generation: number; message: string } } | null)
    ?.taskNotice

  return (
    <div className={styles.today}>
      <title>Сегодня · Идеальный день</title>
      <header className={styles.heading}>
        <div>
          <p className={styles.greeting}>{todayGreeting(now, timezone, name)}</p>
          <h1>
            <time dateTime={date}>{todayDateLabel(date)}</time>
          </h1>
        </div>
        <div className={styles.headerActions}>
          <div className={styles.search}>
            <SearchIcon size={18} />
            <input
              ref={searchInput}
              type="search"
              aria-label="Поиск задач текущего дня"
              placeholder="Поиск задач"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Escape') setSearch('')
              }}
            />
            {search ? (
              <button
                type="button"
                className={styles.clearSearch}
                aria-label="Очистить поиск"
                onClick={() => {
                  setSearch('')
                  searchInput.current?.focus()
                }}
              >
                <XIcon size={16} />
              </button>
            ) : null}
            <kbd aria-hidden="true">⌘</kbd>
          </div>
          <span title="Перепланирование вручную пока недоступно в API. План пересчитывается при изменении задач.">
            <Button variant="secondary" className={styles.replan} disabled>
              <RefreshIcon />
              Перепланировать
            </Button>
          </span>
          <Button
            className={styles.addTask}
            data-new-task-trigger
            onClick={() => navigate(paths.newTask)}
          >
            <PlusIcon />
            Добавить задачу
          </Button>
        </div>
      </header>
      <TodayEnergyProfile date={date} />
      <TodayCriticalDays date={date} />
      {created?.generation === generation ? (
        <div className={styles.notice} role="status">
          <CheckIcon size={18} />
          <div>
            <p className="text-label">Задача добавлена</p>
            <p className="text-caption">
              {created.task.title} · {created.task.planned_date.split('-').reverse().join('.')}
            </p>
            {created.requestedDate && created.requestedDate !== created.task.planned_date ? (
              <p className="text-caption">
                Планировщик перенёс задачу с {created.requestedDate.split('-').reverse().join('.')}{' '}
                на {created.task.planned_date.split('-').reverse().join('.')}.
                {created.task.planned_date !== date ? ' На сегодняшнем таймлайне её не будет.' : ''}
              </p>
            ) : null}
            {created.task.status === 'pending' ? (
              <p className="text-caption">Пока не размещена в расписании.</p>
            ) : null}
          </div>
          <Button
            className={styles.openTask}
            variant="ghost"
            size="s"
            onClick={() => navigate(taskPath(created.task.id))}
          >
            Открыть
          </Button>
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
      <TodayTimeline date={date} search={search} />
      <Outlet />
      {notice?.generation === generation ? (
        <div className={styles.notice} role="status">
          <p>{notice.message}</p>
          <Button
            variant="ghost"
            aria-label="Закрыть уведомление"
            onClick={() => navigate(location.pathname, { replace: true, state: null })}
          >
            <XIcon size={16} />
          </Button>
        </div>
      ) : null}
    </div>
  )
}
