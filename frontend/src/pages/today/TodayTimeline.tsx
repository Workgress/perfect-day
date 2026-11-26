import { useMatch, useNavigate } from 'react-router'
import { paths, taskPath } from '@/app/router/paths'
import { apiError } from '@/shared/api/errors'
import { Button } from '@/shared/ui/button/Button'
import { useSessionStore } from '@/stores/session'
import { DailyTimeline } from './DailyTimeline'
import { TaskDayList } from './TaskDayList'
import { useTodaySchedule } from './useTodaySchedule'
import styles from './TodayPage.module.css'
import dashboardStyles from './TodayDashboard.module.css'
import { TodayPlanSummary } from './TodayPlanSummary'
import { TodayEmptyWindows } from './TodayEmptyWindows'
import { todayWindows } from './todayWindowsModel'

export function TodayTimeline({
  state,
  search = '',
}: {
  state: ReturnType<typeof useTodaySchedule>
  search?: string
}) {
  const navigate = useNavigate()
  const user = useSessionStore((state) => state.user)
  const selected = useMatch(`${paths.taskDetails}/*`)?.params.taskId
  const open = (task: { id: string }) => navigate(taskPath(task.id))
  const create = () => navigate(paths.newTask)
  const query = search.trim().toLocaleLowerCase('ru-RU')
  const matches = (state.day?.tasks ?? state.tasks).filter((task) =>
    `${task.title} ${task.description ?? ''}`.toLocaleLowerCase('ru-RU').includes(query),
  )

  return (
    <div className={styles.plan}>
      {state.loading ? (
        <p className={styles.planState} role="status">
          Загружаем план дня…
        </p>
      ) : state.error ? (
        <section className={styles.planState} role="alert">
          <h2 className="text-heading">Не удалось загрузить план дня</h2>
          <p>{apiError(state.error)}</p>
          <Button variant="secondary" onClick={() => void state.refresh()}>
            Повторить загрузку плана
          </Button>
        </section>
      ) : query ? (
        <section aria-label="Результаты поиска задач">
          <h2 className="text-heading">Поиск задач</h2>
          <p className={styles.searchSummary} role="status">
            {matches.length ? `Найдено: ${matches.length}` : 'На этот день ничего не найдено.'}
          </p>
          <TaskDayList
            title="Задачи текущего дня"
            tasks={matches}
            onTaskSelect={open}
            selectedTaskId={selected}
          />
        </section>
      ) : state.absent && state.tasks.length ? (
        <>
          <section className={styles.planState} role="status">
            <h2 className="text-heading">Расписание на этот день ещё не сохранено</h2>
            <p>Нажмите «Перепланировать», чтобы составить план из задач этого дня.</p>
            {!state.tasks.length ? <p>Задач на этот день пока нет.</p> : null}
          </section>
          <TaskDayList
            title="Задачи на этот день"
            tasks={state.tasks}
            onTaskSelect={open}
            selectedTaskId={selected}
          />
        </>
      ) : state.day ? (
        <div className={dashboardStyles.dashboard}>
          <div className={dashboardStyles.planMain}>
            <DailyTimeline
              day={state.day}
              windows={
                !state.day.tasks.length ? todayWindows(state.day, user?.chronotype) : undefined
              }
              selectedTaskId={selected}
              onTaskSelect={open}
              onCreateTask={create}
            />
          </div>
          {state.day.tasks.length ? (
            <TodayPlanSummary day={state.day} warnings={state.warnings} />
          ) : (
            <TodayEmptyWindows day={state.day} />
          )}
        </div>
      ) : null}
    </div>
  )
}
