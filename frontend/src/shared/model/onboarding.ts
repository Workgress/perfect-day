import type { TaskType } from './task'

export type { TaskType } from './task'
export { TASK_TYPES } from './task'

export type Chronotype = 'lark' | 'owl' | 'dove'

export type OnboardingTask = {
  id: string
  title: string
  type: TaskType
  durationMin: number
}

export type OnboardingDraft = {
  birthDate: string
  birthTime: string
  chronotype: Chronotype
  workStart: string
  workEnd: string
  sleepTime: string
  tasks: OnboardingTask[]
  completion?: { key: string; body: OnboardingRequest }
}

export type OnboardingRequest = {
  planned_date: string
  tasks: { title: string; type: TaskType; duration_min: number }[]
}

export const EMPTY_ONBOARDING: OnboardingDraft = {
  birthDate: '',
  birthTime: '',
  chronotype: 'lark',
  workStart: '08:00',
  workEnd: '18:00',
  sleepTime: '23:00',
  tasks: [],
}
