export const paths = {
  login: '/login',
  register: '/register',
  verifyEmail: '/verify-email',
  onboarding: {
    root: '/onboarding',
    birthDate: '/onboarding/birth-date',
    chronotype: '/onboarding/chronotype',
    firstTasks: '/onboarding/first-tasks',
  },
  today: '/today',
  newTask: '/today/new',
  calendar: '/calendar',
  biorhythms: '/biorhythms',
  settings: '/settings',
  kit: '/dev/kit',
  editTaskPreview: '/dev/tasks/edit',
} as const
