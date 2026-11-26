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
import { useTodaySchedule } from './useTodaySchedule'
import { useScheduleReplan } from './useScheduleReplan'
import { ActionConfirmation } from './ActionConfirmation'
import { ReplanReview } from './ReplanReview'
import confirmationStyles from './ActionConfirmation.module.css'

export function TodayPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const generation = useSessionStore((state) => state.generation)
  const timezone = useSessionStore((state) => state.timezone)
  const user = useSessionStore((state) => state.user)
  const name = user?.name
  const now = useCurrentTime()
  const date = localDate(now, timezone)
  const plan = useTodaySchedule(
    date,
    generation,
    {
      timezone,
      work_start: user?.workStart,
      work_end: user?.workEnd,
    },
    now,
  )
  const replan = useScheduleReplan(date, generation, timezone)
  const [replanConfirmation, setReplanConfirmation] = useState<{
    date: string
    generation: number
    version: number
  } | null>(null)
  const [reviewOpen, setReviewOpen] = useState(false)
  const confirmReplan = () => {
    if (plan.version !== undefined)
      setReplanConfirmation({ date, generation, version: plan.version })
  }
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
  const notice = (
    location.state as {
      taskNotice?: { generation: number; message: string; detail?: string }
    } | null
  )?.taskNotice

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
          <Button
            variant="secondary"
            className={styles.replan}
            disabled={
              plan.version === undefined ||
              replan.pending ||
              replan.taskPending ||
              replan.blocked ||
              location.pathname !== paths.today
            }
            aria-busy={replan.pending}
            onClick={confirmReplan}
          >
            <RefreshIcon />
            {replan.pending ? 'Обновляем план…' : 'Перепланировать'}
          </Button>
          <Button
            className={styles.addTask}
            data-new-task-trigger
            disabled={replan.pending || replan.blocked}
            onClick={() => navigate(paths.newTask)}
          >
            <PlusIcon />
            Добавить задачу
          </Button>
        </div>
      </header>
      {replan.message ? (
        <div className={styles.replanFeedback} role={replan.blocked ? 'alert' : 'status'}>
          <p>{replan.message}</p>
          {replan.review ? (
            <Button variant="ghost" size="s" onClick={() => setReviewOpen(true)}>
              Посмотреть изменения
            </Button>
          ) : null}
          {replan.blocked ? (
            <Button
              variant="secondary"
              size="s"
              disabled={replan.pending}
              onClick={() => void replan.execute(0, true)}
            >
              Обновить данные плана
            </Button>
          ) : null}
        </div>
      ) : null}
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
      <TodayTimeline
        key={`${generation}:${date}:${timezone}`}
        state={plan}
        search={search}
        onReplan={plan.version === undefined ? undefined : confirmReplan}
        replanDisabled={
          plan.version === undefined ||
          replan.pending ||
          replan.taskPending ||
          replan.blocked ||
          location.pathname !== paths.today
        }
      />
      <TodayEnergyProfile date={date} />
      <TodayCriticalDays date={date} />
      <Outlet />
      {replanConfirmation?.generation === generation && replanConfirmation.date === date ? (
        <ActionConfirmation
          title="Перепланировать день?"
          onClose={() => setReplanConfirmation(null)}
          busy={replan.pending}
        >
          <p className={confirmationStyles.secondary}>
            Подберём время для незакреплённых задач. Закреплённые, начатые и выполненные задачи
            сохранятся. Даты задач не изменятся.
          </p>
          <p className={confirmationStyles.secondary}>
            Новый план будет сохранён сразу. Затем можно посмотреть, что изменилось.
          </p>
          {!replan.pending && plan.version !== replanConfirmation.version ? (
            <p role="alert">План изменился. Закройте окно и проверьте данные перед пересчётом.</p>
          ) : null}
          <div className={confirmationStyles.stack}>
            <Button
              disabled={
                replan.pending || replan.taskPending || plan.version !== replanConfirmation.version
              }
              onClick={async () => {
                await replan.execute(replanConfirmation.version)
                setReplanConfirmation(null)
              }}
            >
              {replan.pending ? 'Обновляем план…' : 'Пересчитать план'}
            </Button>
            <Button
              variant="ghost"
              data-confirm-cancel
              disabled={replan.pending}
              onClick={() => setReplanConfirmation(null)}
            >
              Отмена
            </Button>
          </div>
        </ActionConfirmation>
      ) : null}
      {reviewOpen && replan.review ? (
        <ReplanReview
          review={replan.review}
          tasks={plan.tasks}
          now={now}
          onClose={() => setReviewOpen(false)}
        />
      ) : null}
      {notice?.generation === generation ? (
        <div className={styles.notice} role="status">
          <CheckIcon size={18} />
          <div>
            <p className="text-label">{notice.message}</p>
            {notice.detail ? <p className="text-caption">{notice.detail}</p> : null}
          </div>
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
