import { useState } from 'react'
import { DAILY_SCHEDULE_FIXTURES, PLANNING_FIXTURE_CONTEXT } from '@/shared/fixtures/planning'
import type { Task } from '@/shared/model/task'
import { Button } from '@/shared/ui/button/Button'
import { PageHeader } from '@/shared/ui/page-header/PageHeader'
import { EditTaskDialog } from './EditTaskDialog'
import type { TaskFormOptions } from './taskFormSettings'
import styles from './EditTaskPreviewPage.module.css'

const task = DAILY_SCHEDULE_FIXTURES.normal.tasks[2]
const EXAMPLES: { label: string; task: Task; options: TaskFormOptions }[] = [
  { label: 'Обычная задача', task, options: { recurrence: null, reminderMinutes: 15 } },
  {
    label: 'Закреплённое время',
    task: DAILY_SCHEDULE_FIXTURES.normal.tasks[4],
    options: { recurrence: null, reminderMinutes: 30 },
  },
  {
    label: 'Повторение и своя длительность',
    task: { ...task, id: 'preview-recurring', duration_min: 75 },
    options: {
      recurrence: { frequency: 'weekly', interval: 2, weekdays: [1, 3, 5], until: '2026-12-30' },
      reminderMinutes: 10,
    },
  },
  {
    label: 'Прошедший дедлайн',
    task: {
      ...task,
      id: 'preview-expired',
      planned_date: '2026-11-10',
      deadline: '2026-11-10T09:00:00Z',
    },
    options: { recurrence: null, reminderMinutes: null },
  },
]

const CONTEXT = {
  timezone: PLANNING_FIXTURE_CONTEXT.timezone,
  now: new Date(PLANNING_FIXTURE_CONTEXT.now),
  workStart: '08:00',
  workEnd: '18:00',
}

export function EditTaskPreviewPage() {
  const [active, setActive] = useState<number | null>(0)
  const example = active === null ? null : EXAMPLES[active]
  return (
    <main className={styles.page}>
      <title>Предпросмотр редактирования · Идеальный день</title>
      <PageHeader
        title="Редактирование задачи"
        description="Предпросмотр формы на тестовых данных за 11 ноября 2026 года. Изменения в план не сохраняются."
      />
      <div className={styles.examples} role="group" aria-label="Примеры задач">
        {EXAMPLES.map((item, index) => (
          <Button
            key={item.label}
            variant="secondary"
            data-task-edit-trigger
            onClick={() => setActive(index)}
          >
            {item.label}
          </Button>
        ))}
      </div>
      {example ? (
        <EditTaskDialog
          task={example.task}
          options={example.options}
          context={CONTEXT}
          onCancel={() => setActive(null)}
        />
      ) : null}
    </main>
  )
}
