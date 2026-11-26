import { Link } from 'react-router'
import { taskPath } from '@/app/router/paths'
import { apiError } from '@/shared/api/errors'
import { plannerMessage } from '@/shared/lib/plannerText'
import type { DailySchedule, SavedSchedule } from '@/shared/model/schedule'
import { Button } from '@/shared/ui/button/Button'
import { SparklesIcon, AlertTriangleIcon, CoffeeIcon } from '@/shared/ui/icon/icons'
import { formatDate } from '@/pages/biorhythms/biorhythmChartModel'
import { timelineClock, timelineDuration } from './timelineModel'
import styles from './TodayDashboard.module.css'

export type PlannerHintsState = { loading: boolean; error: unknown; refresh: () => void }
const TITLES: Record<string, string> = {
  OVERLOAD: 'Можно разгрузить день',
  CRITICAL_DAY: 'Снизьте нагрузку по самочувствию',
  CYCLE_MINIMUM: 'По модели — меньше нагрузки',
  INTELLECTUAL_PEAK: 'Интеллектуальный цикл',
  PHYSICAL_PEAK: 'Физический цикл',
  EMOTIONAL_PEAK: 'Эмоциональный цикл',
  ALTERNATING_TYPES: 'Чередуйте типы задач',
  CRITICAL_REST_UNAVAILABLE: 'Не хватает времени на отдых',
  MOVE_RECOMMENDATION_UNAVAILABLE: 'Дата переноса не найдена',
  CRITICAL_MOVE_UNAVAILABLE: 'Перенос недоступен',
}

export function PlannerHints({
  day,
  warnings,
  state,
  now,
}: {
  day: DailySchedule
  warnings: SavedSchedule['warnings']
  state?: PlannerHintsState
  now: number
}) {
  const rest = day.slots.find(
    (slot) => (slot.kind === 'break' || slot.kind === 'rest') && Date.parse(slot.start_at) > now,
  )
  const items = warnings.filter((item) => item.code !== 'SUGGESTED_MOVE')
  return (
    <section className={styles.tips} aria-label="Подсказки планировщика">
      <h2>Подсказки</h2>
      {rest ? (
        <div className={styles.hint}>
          <CoffeeIcon size={16} />
          <div>
            <h3>Перерыв в {timelineClock(Date.parse(rest.start_at), day.timezone)}</h3>
            <p>
              {timelineDuration((Date.parse(rest.end_at) - Date.parse(rest.start_at)) / 60_000)}{' '}
              отдыха в расписании.
            </p>
            <details className={styles.hintDetails}>
              <summary>Почему так?</summary>
              <p>Перерыв между интенсивными задачами</p>
            </details>
          </div>
        </div>
      ) : null}
      {items.map((warning, index) => {
        const task = day.tasks.find((task) => task.id === warning.task_id)
        const move = day.planning?.schedule.moves.find(
          (move) => move.task_id === warning.task_id && move.reason_code === warning.code,
        )
        const Icon = warning.level === 'info' ? SparklesIcon : AlertTriangleIcon
        return (
          <div
            className={styles.hint}
            data-level={warning.level}
            key={`${warning.code}:${warning.task_id}:${index}`}
          >
            <Icon size={16} />
            <div>
              <h3>
                {move
                  ? `Задача перенесена на ${formatDate(move.to_date, { day: 'numeric', month: 'long' })}`
                  : (TITLES[warning.code] ?? 'Обратите внимание')}
              </h3>
              {task ? <Link to={taskPath(task.id)}>{task.title}</Link> : null}
              {!task && move ? (
                <Link to={taskPath(move.task_id)}>Открыть перенесённую задачу</Link>
              ) : null}
              <p>{plannerMessage(warning.message)}</p>
            </div>
          </div>
        )
      })}
      {state?.loading ? (
        <p className={styles.context}>Загружаем пояснения и предложения…</p>
      ) : state?.error ? (
        <div className={styles.hintState}>
          <p>Подсказки временно недоступны. {apiError(state.error)}</p>
          <Button variant="ghost" size="s" onClick={state.refresh}>
            Обновить подсказки и план
          </Button>
        </div>
      ) : !rest && !items.length && !day.planning?.recommendations.length ? (
        <p className={styles.context}>Дополнительных предложений по этому плану нет.</p>
      ) : null}
    </section>
  )
}
