export const paths = {
  login: '/login',
  register: '/register',
  verifyEmail: '/verify-email',
  verificationSent: '/verify-email/sent',
  resetPassword: '/reset-password',
  onboarding: {
    root: '/onboarding',
    birthDate: '/onboarding/birth-date',
    chronotype: '/onboarding/chronotype',
    firstTasks: '/onboarding/first-tasks',
  },
  today: '/today',
  newTask: '/today/new',
  taskDetails: '/today/tasks/:taskId',
  editTask: '/today/tasks/:taskId/edit',
  calendar: '/calendar',
  biorhythms: '/biorhythms',
  settings: '/settings',
  kit: '/dev/kit',
  editTaskPreview: '/dev/tasks/edit',
  timelinePreview: '/dev/timeline',
} as const

export const taskPath = (id: string) => `/today/tasks/${encodeURIComponent(id)}`
export const editTaskPath = (id: string) => `${taskPath(id)}/edit`
