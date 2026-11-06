import type { OnboardingRequest } from './onboarding'

export type PlanPreview = {
  planned_date: string
  timezone: string
  slots: {
    task_index: number
    start_time: string
    end_time: string
    explanation: string
  }[]
  unscheduled_task_indexes: number[]
  local?: boolean
}

export type PlanPreviewRequest = OnboardingRequest
