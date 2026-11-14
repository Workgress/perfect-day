import { useState } from 'react'
import { DAILY_SCHEDULE_FIXTURES, PLANNING_FIXTURE_CONTEXT } from '@/shared/fixtures/planning'
import type { DailySchedule } from '@/shared/model/schedule'
import type { Task, TaskCreateRequest } from '@/shared/model/task'
import { PageHeader } from '@/shared/ui/page-header/PageHeader'
import * as Segment from '@/shared/ui/segment/Segment'
import { DailyTimeline } from './DailyTimeline'
import { EditTaskDialog } from './EditTaskDialog'
import { TaskDialog } from './TaskDialog'
import { TaskForm } from './TaskForm'
import { TaskDetailsPanel } from './TaskDetailsPanel'
import { emptyTaskForm, type TaskFormContext } from './taskFormModel'
import type { TaskFormOptions } from './taskFormSettings'
import styles from './TimelinePreviewPage.module.css'

const EXAMPLES = [
  { value: 'normal', label: 'Обычный день' },
  { value: 'empty', label: 'Пустой день' },
] as const
type Example = (typeof EXAMPLES)[number]['value']
const NOW = new Date(PLANNING_FIXTURE_CONTEXT.now)

export function TimelinePreviewPage() {
  const [example, setExample] = useState<Example>('normal')
  return (
    <main className={styles.page}>
      <title>Предпросмотр таймлайна · Идеальный день</title>
      <PageHeader
        title="Суточный таймлайн"
        description="Предпросмотр на тестовых данных: 11 ноября 2026 года, 09:42. Изменения в план не сохраняются."
      />
      <Segment.Root
        className={styles.examples}
        aria-label="Примеры дней"
        value={example}
        onValueChange={(value) => setExample(value as Example)}
      >
        {EXAMPLES.map((item) => (
          <Segment.Item key={item.value} value={item.value}>
            {item.label}
          </Segment.Item>
        ))}
      </Segment.Root>
      <div className={styles.content}>
        <TimelineExample key={example} day={DAILY_SCHEDULE_FIXTURES[example]} />
      </div>
    </main>
  )
}

function TimelineExample({ day }: { day: DailySchedule }) {
  const [selected, setSelected] = useState<Task | null>(null)
  const [editing, setEditing] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [importNotice, setImportNotice] = useState(false)
  const [creation, setCreation] = useState<{ date: string; preferredStart?: string } | null>(null)
  const context = {
    timezone: day.timezone,
    now: NOW,
    workStart: day.work_start.slice(0, 5),
    workEnd: day.work_end.slice(0, 5),
  }
  return (
    <>
      <DailyTimeline
        day={day}
        now={NOW}
        selectedTaskId={selected?.id}
        onTaskSelect={(task) => {
          setSelected(task)
          setEditing(false)
          setNotice(null)
        }}
        onCreateTask={(date, preferredStart) => setCreation({ date, preferredStart })}
        onImportCalendar={() => setImportNotice(true)}
      />
      {importNotice ? <p role="status">Импорт из календаря пока не подключён.</p> : null}
      {selected && !editing ? (
        <TaskDetailsPanel
          task={selected}
          slots={day.slots}
          timezone={day.timezone}
          now={NOW}
          onClose={() => setSelected(null)}
          onEdit={() => setEditing(true)}
          onMove={() => setEditing(true)}
          onPin={() => setEditing(true)}
          onStart={() => setNotice('В предпросмотре запуск задачи не изменяет план.')}
          notice={notice}
        />
      ) : null}
      {selected && editing ? (
        <EditTaskDialog task={selected} context={context} onCancel={() => setEditing(false)} />
      ) : null}
      {creation ? (
        <CreationPreview
          context={context}
          date={creation.date}
          preferredStart={creation.preferredStart}
          onClose={() => setCreation(null)}
        />
      ) : null}
    </>
  )
}

function CreationPreview({
  context,
  date,
  preferredStart,
  onClose,
}: {
  context: TaskFormContext
  date: string
  preferredStart?: string
  onClose: () => void
}) {
  const [preview, setPreview] = useState<{
    request: TaskCreateRequest
    options: TaskFormOptions
  } | null>(null)
  return (
    <TaskDialog
      title="Новая задача"
      description="Название, тип и длительность — обязательны."
      onClose={onClose}
    >
      <TaskForm
        context={context}
        initialValues={{
          ...emptyTaskForm(context.timezone, context.now),
          plannedDate: date,
          preferredStart: preferredStart ?? '',
        }}
        onCancel={onClose}
        onSubmit={(request, options) => setPreview({ request, options })}
        preview={preview?.request}
        previewOptions={preview?.options}
        onChange={() => setPreview(null)}
      />
    </TaskDialog>
  )
}
