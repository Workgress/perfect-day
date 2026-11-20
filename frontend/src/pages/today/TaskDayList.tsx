import { useId } from 'react'
import { TASK_TYPES, type Task } from '@/shared/model/task'
import { timelineDuration } from './timelineModel'
import styles from './TaskDayList.module.css'

const STATUS = {
  pending: 'Без времени',
  scheduled: 'Размещение не подтверждено',
  done: 'Выполнена',
  skipped: 'Пропущена',
}

export function TaskDayList({
  title,
  tasks,
  onTaskSelect,
  selectedTaskId,
}: {
  title: string
  tasks: Task[]
  onTaskSelect?: (task: Task) => void
  selectedTaskId?: string | null
}) {
  const id = useId()
  if (!tasks.length) return null
  return (
    <section className={styles.section} aria-labelledby={id}>
      <h3 id={id} className="text-heading">
        {title}
      </h3>
      <ul className={styles.list}>
        {tasks.map((task) => {
          const content = (
            <>
              <span className={styles.title}>{task.title}</span>
              <span className={styles.meta}>
                {TASK_TYPES[task.type]} · {timelineDuration(task.duration_min)} ·{' '}
                {STATUS[task.status]}
              </span>
            </>
          )
          return (
            <li key={task.id}>
              {onTaskSelect ? (
                <button
                  type="button"
                  className={styles.task}
                  data-task-details-trigger
                  data-task-edit-trigger
                  aria-haspopup="dialog"
                  aria-expanded={task.id === selectedTaskId}
                  onClick={() => onTaskSelect(task)}
                >
                  {content}
                </button>
              ) : (
                <div className={styles.task}>{content}</div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
