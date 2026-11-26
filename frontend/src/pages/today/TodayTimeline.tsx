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
import { usePlannerDetails } from './usePlannerDetails'
import { plannerExplanation } from '@/shared/lib/plannerText'
import { TodayLoading } from './TodayLoading'

export function TodayTimeline({
  state,
  search = '',
  onReplan,
  replanDisabled = false,
}: {
  state: ReturnType<typeof useTodaySchedule>
  search?: string
  onReplan?: () => void
  replanDisabled?: boolean
}) {
  const navigate = useNavigate()
  const user = useSessionStore((state) => state.user)
  const details = usePlannerDetails(
    state.day?.schedule
      ? {
          ...state.day.schedule,
          planned_date: state.day.date,
          timezone: state.day.timezone,
        }
      : null,
  )
  const day = state.day
    ? {
        ...state.day,
        planning: details.isSuccess && !details.isFetching ? details.data : undefined,
      }
    : undefined
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
        <TodayLoading />
      ) : state.error ? (
        <section className={styles.planState} role="alert">
          <h2 className="text-heading">Не удалось загрузить план дня</h2>
          <p>{apiError(state.error)}</p>
          <Button variant="secondary" onClick={() => void state.refresh()}>
            Повторить загрузку плана
          </Button>
        </section>
      ) : state.stale ? (
        <>
          <section className={styles.planState} role="status">
            <h2 className="text-heading">Расписание устарело</h2>
            <p>
              В сохранённом плане осталась ссылка на удалённую задачу. Пересчитайте расписание,
              чтобы обновить интервалы и нагрузку.
            </p>
            {onReplan ? (
              <Button variant="secondary" disabled={replanDisabled} onClick={onReplan}>
                Пересчитать расписание
              </Button>
            ) : null}
            <Button variant="ghost" disabled={replanDisabled} onClick={() => void state.refresh()}>
              Повторить загрузку плана
            </Button>
          </section>
          <TaskDayList
            title={query ? 'Результаты поиска задач' : 'Задачи на этот день'}
            tasks={matches}
            onTaskSelect={open}
            selectedTaskId={selected}
          />
          {!matches.length ? (
            <p className={styles.searchSummary}>
              {query ? 'На этот день ничего не найдено.' : 'Задач на этот день пока нет.'}
            </p>
          ) : null}
        </>
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
              day={day!}
              windows={
                !state.day.tasks.length ? todayWindows(state.day, user?.chronotype) : undefined
              }
              selectedTaskId={selected}
              onTaskSelect={open}
              onCreateTask={create}
            />
            <TaskDayList
              title="Без времени"
              tasks={day!.tasks.filter(
                (task) => task.planned_date === day!.date && task.status === 'pending',
              )}
              explanations={Object.fromEntries(
                day!.planning?.unscheduled_explanations.map((item) => [
                  item.task_id,
                  plannerExplanation(item.explanation),
                ]) ?? [],
              )}
              onTaskSelect={open}
              selectedTaskId={selected}
            />
          </div>
          {state.day.tasks.length ? (
            <TodayPlanSummary
              day={day!}
              warnings={state.warnings}
              plannerState={{
                loading: details.isPending || details.isFetching,
                error: details.error,
                refresh: () => {
                  void details.refetch()
                  void state.refresh()
                },
              }}
            />
          ) : (
            <TodayEmptyWindows day={state.day} />
          )}
        </div>
      ) : null}
    </div>
  )
}
