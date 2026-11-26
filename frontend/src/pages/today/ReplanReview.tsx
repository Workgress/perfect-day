import type { SavedSchedule } from '@/shared/model/schedule'
import type { Task } from '@/shared/model/task'
import { Button } from '@/shared/ui/button/Button'
import { ActionConfirmation } from './ActionConfirmation'
import { taskTimeLabel } from './taskTimeOptions'
import { timelineDuration } from './timelineModel'
import styles from './ActionConfirmation.module.css'

export function scheduleChanges(before: SavedSchedule | undefined, after: SavedSchedule) {
  const intervals = (schedule?: SavedSchedule) => {
    const result = new Map<string, { start_at: string; end_at: string }[]>()
    for (const slot of schedule?.slots ?? []) {
      if (slot.kind !== 'task') continue
      const list = result.get(slot.task_id) ?? []
      list.push({ start_at: slot.start_at, end_at: slot.end_at })
      result.set(slot.task_id, list)
    }
    for (const list of result.values())
      list.sort((a, b) => Date.parse(a.start_at) - Date.parse(b.start_at))
    return result
  }
  const old = intervals(before),
    next = intervals(after)
  return [...new Set([...old.keys(), ...next.keys()])].flatMap((id) => {
    const a = old.get(id) ?? [],
      b = next.get(id) ?? []
    const same =
      a.length === b.length &&
      a.every(
        (value, i) =>
          Date.parse(value.start_at) === Date.parse(b[i].start_at) &&
          Date.parse(value.end_at) === Date.parse(b[i].end_at),
      )
    return same ? [] : [{ id, before: a, after: b }]
  })
}

export function ReplanReview({
  review,
  tasks,
  now,
  onClose,
}: {
  review: { before?: SavedSchedule; after: SavedSchedule }
  tasks: Task[]
  now: Date
  onClose: () => void
}) {
  const changes = scheduleChanges(review.before, review.after)
  const label = (list: { start_at: string; end_at: string }[]) =>
    list.length
      ? list
          .map((slot) => taskTimeLabel(slot.start_at, slot.end_at, review.after.timezone, now))
          .join(', ')
      : 'Без времени'
  return (
    <ActionConfirmation title="Результат перепланирования" wide onClose={onClose}>
      <p className={styles.secondary}>
        Изменения уже сохранены. Закреплённые, начатые и выполненные задачи сохраняются при
        пересчёте.
      </p>
      {changes.length ? (
        <ul className={styles.changes}>
          {changes.map((change) => (
            <li key={change.id}>
              <strong>{tasks.find((task) => task.id === change.id)?.title ?? 'Задача'}</strong>
              <p>
                Было: <time>{label(change.before)}</time>
              </p>
              <p>
                Стало: <time>{label(change.after)}</time>
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <p>Время задач не изменилось: текущий план уже подходит под ограничения.</p>
      )}
      <p>
        Нагрузка: {review.before ? `${timelineDuration(review.before.metrics.planned_min)} → ` : ''}
        {timelineDuration(review.after.metrics.planned_min)} из{' '}
        {timelineDuration(review.after.metrics.capacity_min)}.
      </p>
      {review.after.unscheduled.length ? (
        <p>Без времени: {review.after.unscheduled.length}. Пояснения доступны в списке задач.</p>
      ) : null}
      <div className={styles.stack}>
        <Button data-confirm-cancel onClick={onClose}>
          К плану
        </Button>
      </div>
    </ActionConfirmation>
  )
}
