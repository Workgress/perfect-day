import type { Task } from './task'

/** Timeline slot; the API adds reason_codes to this representation. */
export type ScheduleSlot = {
  id: string
  /** Absolute timestamps. Render them in DailySchedule.timezone. */
  start_at: string
  end_at: string
  explanation: string | null
  is_pinned: boolean
} & ({ kind: 'task'; task_id: string } | { kind: 'break' | 'lunch' | 'rest'; task_id: null })

/** GET /schedule?date=YYYY-MM-DD. Tasks and work clocks are not included. */
export type SavedSchedule = {
  id: string
  planned_date: string
  timezone: string
  version: number
  algorithm_version: string
  generated_at: string
  slots: (ScheduleSlot & { reason_codes: string[] })[]
  unscheduled: { task_id: string; reason_codes: string[] }[]
  metrics: {
    requested_min: number
    planned_min: number
    capacity_min: number
    high_intensity_min: number
    critical_level: number
    load_factor: number
    moved_min: number
  }
  warnings: {
    code: string
    message: string
    level: 'info' | 'warning' | 'critical'
    task_id: string | null
    target_date: string | null
  }[]
  moves: { task_id: string; from_date: string; to_date: string; reason_code: string }[]
}

/** View model assembled from a saved schedule, task responses and work clocks. */
export type DailySchedule = {
  planning?: SchedulePlanningDetails
  /** Local date YYYY-MM-DD; work clocks are local HH:mm:ss. */
  date: string
  timezone: string
  work_start: string
  work_end: string
  schedule: { id: string; version: number } | null
  tasks: Task[]
  /** Sorted, non-overlapping occupied intervals; gaps represent free time. */
  slots: ScheduleSlot[]
  /** Pending tasks that did not fit, excluding done and skipped tasks. */
  unscheduled_task_ids: string[]
}

export type TaskMoveRecommendation = {
  task_id: string
  from_date: string
  to_date: string
  reason_code: string
  explanation: string
}

export type SchedulePlanningDetails = {
  schedule: SavedSchedule
  recommendations: TaskMoveRecommendation[]
  placement_explanations: {
    task_id: string
    planned_date: string
    start_at: string
    end_at: string
    preservation: 'pinned' | 'done' | 'started' | 'past' | 'system' | null
    reason_codes: string[]
    explanation: string
  }[]
  unscheduled_explanations: {
    task_id: string
    planned_date: string
    reason_codes: string[]
    explanation: string
  }[]
}
