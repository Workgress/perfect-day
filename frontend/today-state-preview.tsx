import { createRoot } from 'react-dom/client'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from './src/shared/api/queryClient'
import { AppLayout } from './src/app/layouts/AppLayout'
import { TodayPage } from './src/pages/today/TodayPage'
import { TaskPage } from './src/pages/today/TaskPage'
import { TaskDialog } from './src/pages/today/TaskDialog'
import { TaskForm } from './src/pages/today/TaskForm'
import { ReplanReview } from './src/pages/today/ReplanReview'
import { emptyTaskForm } from './src/pages/today/taskFormModel'
import { DAILY_SCHEDULE_FIXTURES } from './src/shared/fixtures/planning'
import { savedFixture, planningDetails } from './src/test/planningDetails'
import { createBiorhythmDemoPoints } from './src/shared/fixtures/biorhythms'
import { useSessionStore } from './src/stores/session'
import './src/shared/styles/global.css'
const params = new URLSearchParams(location.search)
const mode = params.get('case') ?? 'end'
document.documentElement.dataset.theme = params.get('theme') ?? 'light'
const NativeDate = Date
const fixed = NativeDate.parse(`2026-11-11T${mode === 'end' ? '13:30' : '04:42'}:00Z`)
window.Date = new Proxy(NativeDate, {
  construct(target, args) {
    return Reflect.construct(target, args.length ? args : [fixed])
  },
  get(target, prop) {
    return prop === 'now' ? () => fixed : Reflect.get(target, prop)
  },
})
const day = structuredClone(DAILY_SCHEDULE_FIXTURES.normal)
if (mode === 'end')
  day.tasks = day.tasks.map((task, i) => ({ ...task, status: i === 5 ? 'skipped' : 'done' }))
let saved = savedFixture(day)
const taskId = day.tasks[2].id
useSessionStore.getState().signIn({
  accessToken: 'preview-only',
  user: {
    id: 'preview',
    name: 'Анна',
    birthDate: '2003-09-20',
    chronotype: 'lark',
    workStart: '08:00',
    workEnd: '18:00',
  },
})
useSessionStore.setState({ ownerId: 'preview', timezone: day.timezone, isOnboarded: true })
window.fetch = async (input, init) => {
  const url = new URL(String(input), location.origin)
  if (mode === 'loading' && !url.pathname.includes('health')) return new Promise(() => {})
  if (url.pathname.endsWith('/biorhythms'))
    return Response.json({
      start: url.searchParams.get('from'),
      end: url.searchParams.get('to'),
      step: 'day',
      period: null,
      timezone: day.timezone,
      algorithm_version: 'test',
      points: createBiorhythmDemoPoints(url.searchParams.get('from')!, url.searchParams.get('to')!),
    })
  if (url.pathname.endsWith('/critical-days'))
    return Response.json({
      start: url.searchParams.get('from'),
      end: url.searchParams.get('to'),
      timezone: day.timezone,
      algorithm_version: 'test',
      days: [],
    })
  if (url.pathname.endsWith('/schedule/details')) return Response.json(planningDetails(saved))
  if (url.pathname.endsWith('/schedule')) {
    if (mode === 'deadline')
      return Response.json({
        ...saved,
        planned_date: url.searchParams.get('date'),
        slots: [
          {
            ...saved.slots[0],
            kind: 'task',
            task_id: taskId,
            start_at: '2026-11-11T03:00:00Z',
            end_at: '2026-11-11T13:00:00Z',
            reason_codes: [],
          },
        ],
      })
    return Response.json({ ...saved, planned_date: url.searchParams.get('date') })
  }
  if (url.pathname.endsWith('/move')) {
    const body = JSON.parse(String(init?.body))
    const task = day.tasks.find((t) => t.id === taskId)!
    Object.assign(task, {
      planned_date: body.planned_date,
      pinned_start: body.start_at,
      is_pinned: true,
      version: task.version + 1,
    })
    saved.slots = saved.slots.filter((s) => s.task_id !== taskId)
    saved.version++
    return Response.json(task)
  }
  if (url.pathname.endsWith('/tasks')) {
    const tasks = day.tasks.filter((t) => t.planned_date === url.searchParams.get('date'))
    return Response.json({ items: tasks, total: tasks.length, limit: 100, offset: 0 })
  }
  if (url.pathname.endsWith(taskId)) {
    if (init?.method === 'DELETE') {
      day.tasks = day.tasks.filter((t) => t.id !== taskId)
      saved.slots = saved.slots.filter((s) => s.task_id !== taskId)
      return new Response(null, { status: 204 })
    }
    return Response.json(day.tasks.find((t) => t.id === taskId))
  }
  return Response.json({ status: 'ok' })
}
const after = {
  ...saved,
  slots: saved.slots.map((s) =>
    s.task_id === taskId
      ? { ...s, start_at: '2026-11-11T07:00:00Z', end_at: '2026-11-11T08:30:00Z' }
      : s,
  ),
}
const create = (
  <TaskDialog
    title="Новая задача"
    description="Название, тип и длительность — обязательны."
    onClose={() => {}}
  >
    <TaskForm
      apiConnected
      allowPinning
      context={{ timezone: day.timezone, now: new Date(), workStart: '08:00', workEnd: '18:00' }}
      initialValues={{
        ...emptyTaskForm(day.timezone),
        title: 'Презентация по проекту',
        durationMin: 60,
        type: 'creative',
        deadlineLocal: `${day.date}T18:00`,
      }}
      onCancel={() => {}}
      onSubmit={() => {}}
    />
  </TaskDialog>
)
const router = createMemoryRouter(
  [
    {
      element: <AppLayout />,
      children: [
        {
          path: '/today',
          element: <TodayPage />,
          children: [
            { path: 'tasks/:taskId', element: <TaskPage /> },
            { path: 'tasks/new', element: create },
          ],
        },
      ],
    },
  ],
  {
    initialEntries: [
      mode === 'delete' || mode === 'move'
        ? `/today/tasks/${taskId}`
        : mode === 'deadline'
          ? '/today/tasks/new'
          : '/today',
    ],
  },
)
createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={createQueryClient()}>
    <RouterProvider router={router} />
    {mode === 'review' ? (
      <ReplanReview
        review={{ before: saved, after }}
        tasks={day.tasks}
        now={new Date()}
        onClose={() => {}}
      />
    ) : null}
  </QueryClientProvider>,
)
