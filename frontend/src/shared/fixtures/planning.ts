import type { DailySchedule, ScheduleSlot } from '@/shared/model/schedule'
import type { Task, TaskFields, TaskFormValues, TaskPlacement } from '@/shared/model/task'

/** Fixed demo clock; no account data, network requests or browser storage. */
export const PLANNING_FIXTURE_CONTEXT = {
  date: '2026-11-11',
  timezone: 'Asia/Yekaterinburg',
  now: '2026-11-11T04:42:00Z',
} as const

function timestamp(clock: string): string {
  // Fixed +05:00 fixture timezone. This is not an adapter for user-entered dates.
  return new Date(`${PLANNING_FIXTURE_CONTEXT.date}T${clock}:00+05:00`).toISOString()
}

function fixtureId(group: number, index: number): string {
  return `${group}0000000-0000-4000-8000-${String(index).padStart(12, '0')}`
}

function task(
  index: number,
  fields: Partial<TaskFields> & Partial<Pick<Task, 'status' | 'completed_at'>>,
  placement: TaskPlacement = { is_pinned: false, pinned_start: null },
): Task {
  return {
    id: fixtureId(1, index),
    title: 'Задача для вёрстки',
    description: null,
    type: 'routine',
    priority: 'medium',
    duration_min: 30,
    planned_date: PLANNING_FIXTURE_CONTEXT.date,
    preferred_start: null,
    deadline: null,
    status: 'scheduled',
    completed_at: null,
    version: 1,
    ...fields,
    ...placement,
  }
}

const normalTasks: Task[] = [
  task(1, {
    title: 'Разобрать почту',
    status: 'done',
    completed_at: timestamp('08:30'),
  }),
  task(2, {
    title: 'Повторить конспект',
    type: 'intellectual',
    duration_min: 60,
    status: 'done',
    completed_at: timestamp('09:30'),
  }),
  task(3, {
    title: 'Подготовка к экзамену',
    description: 'Решить задания и выписать вопросы преподавателю.',
    type: 'intellectual',
    duration_min: 90,
    priority: 'high',
    preferred_start: '10:00:00',
    deadline: timestamp('14:00'),
  }),
  task(4, {
    title: 'Подготовить концепцию презентации проекта и примеры для обсуждения с командой',
    description: 'Длинное название для проверки переноса строк. Собрать идеи и набросать слайды.',
    type: 'creative',
    duration_min: 60,
    deadline: '2026-11-13T13:00:00Z',
  }),
  task(
    5,
    { title: 'Тренировка в зале', type: 'physical', duration_min: 60 },
    { is_pinned: true, pinned_start: timestamp('15:00') },
  ),
  task(6, { title: 'Оформить список литературы', duration_min: 60, priority: 'low' }),
  task(7, { title: 'Разобрать фотографии', type: 'creative', status: 'skipped' }),
]

function taskSlot(index: number, taskIndex: number, start: string, end: string): ScheduleSlot {
  const item = normalTasks[taskIndex]
  return {
    id: fixtureId(2, index),
    kind: 'task',
    task_id: item.id,
    start_at: timestamp(start),
    end_at: timestamp(end),
    is_pinned: item.is_pinned,
    explanation: item.is_pinned
      ? 'Время закреплено пользователем.'
      : 'Демонстрационное размещение для вёрстки, без расчёта биоритмов.',
  }
}

function systemSlot(
  index: number,
  kind: 'break' | 'lunch' | 'rest',
  start: string,
  end: string,
): ScheduleSlot {
  return {
    id: fixtureId(2, index),
    kind,
    task_id: null,
    start_at: timestamp(start),
    end_at: timestamp(end),
    is_pinned: false,
    explanation: 'Демонстрационный интервал отдыха.',
  }
}

const normal: DailySchedule = {
  date: PLANNING_FIXTURE_CONTEXT.date,
  timezone: PLANNING_FIXTURE_CONTEXT.timezone,
  work_start: '08:00:00',
  work_end: '18:00:00',
  schedule: { id: fixtureId(3, 1), version: 1 },
  tasks: normalTasks,
  slots: [
    taskSlot(1, 0, '08:00', '08:30'),
    taskSlot(2, 1, '08:30', '09:30'),
    taskSlot(3, 2, '10:00', '11:30'),
    systemSlot(4, 'break', '11:30', '12:00'),
    systemSlot(5, 'lunch', '12:00', '13:00'),
    taskSlot(6, 3, '13:00', '14:00'),
    systemSlot(7, 'rest', '14:00', '14:30'),
    taskSlot(8, 4, '15:00', '16:00'),
    taskSlot(9, 5, '16:00', '17:00'),
  ],
  unscheduled_task_ids: [],
}

const empty: DailySchedule = {
  date: PLANNING_FIXTURE_CONTEXT.date,
  timezone: PLANNING_FIXTURE_CONTEXT.timezone,
  work_start: '08:00:00',
  work_end: '18:00:00',
  schedule: null,
  tasks: [],
  slots: [],
  unscheduled_task_ids: [],
}

const pendingTasks: Task[] = [
  task(8, {
    title: 'Подготовить отчёт за месяц',
    type: 'intellectual',
    duration_min: 240,
    priority: 'high',
    deadline: timestamp('18:00'),
    status: 'pending',
  }),
  task(9, {
    title: 'Разработать иллюстрации',
    type: 'creative',
    duration_min: 120,
    status: 'pending',
  }),
]

const overloaded: DailySchedule = {
  ...structuredClone(normal),
  schedule: { id: fixtureId(3, 2), version: 1 },
  tasks: [...structuredClone(normalTasks), ...pendingTasks],
  unscheduled_task_ids: pendingTasks.map((item) => item.id),
}

export const DAILY_SCHEDULE_FIXTURES = { normal, empty, overloaded } satisfies Record<
  string,
  DailySchedule
>

const emptyForm: TaskFormValues = {
  title: '',
  description: '',
  type: '',
  durationMin: '',
  plannedDate: PLANNING_FIXTURE_CONTEXT.date,
  deadlineLocal: '',
  priority: 'medium',
  preferredStart: '',
  isPinned: false,
  pinnedStartLocal: '',
}

const editForm: TaskFormValues = {
  title: normalTasks[2].title,
  description: normalTasks[2].description ?? '',
  type: 'intellectual',
  durationMin: 90,
  plannedDate: PLANNING_FIXTURE_CONTEXT.date,
  deadlineLocal: '2026-11-11T14:00',
  priority: 'high',
  preferredStart: '10:00',
  isPinned: false,
  pinnedStartLocal: '',
}

export const TASK_FORM_FIXTURES = {
  empty: emptyForm,
  edit: editForm,
  pinned: {
    ...editForm,
    title: 'Тренировка в зале',
    description: '',
    type: 'physical',
    durationMin: 60,
    deadlineLocal: '',
    preferredStart: '',
    isPinned: true,
    pinnedStartLocal: '2026-11-11T15:00',
  },
  minDuration: { ...editForm, durationMin: 5 },
  maxDuration: { ...editForm, durationMin: 480 },
  longTitle: { ...editForm, title: normalTasks[3].title },
  invalid: {
    ...emptyForm,
    title: '   ',
    durationMin: 4,
    deadlineLocal: '2026-11-11',
    isPinned: true,
  },
} satisfies Record<string, TaskFormValues>
