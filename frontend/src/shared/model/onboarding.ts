export type Chronotype = 'lark' | 'owl' | 'dove'

export type TaskType = 'intellectual' | 'physical' | 'creative' | 'routine'

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
  planReady: boolean
}

export const EMPTY_ONBOARDING: OnboardingDraft = {
  birthDate: '',
  birthTime: '',
  chronotype: 'lark',
  workStart: '08:00',
  workEnd: '18:00',
  sleepTime: '23:00',
  tasks: [],
  planReady: false,
}

export const TASK_TYPES: Record<TaskType, string> = {
  intellectual: 'Интеллектуальная',
  physical: 'Физическая',
  creative: 'Творческая',
  routine: 'Рутина',
}
