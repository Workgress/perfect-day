import type { Task } from './task'

/** Saved schedule proposal; separate from the onboarding PlanPreview. */
export type ScheduleSlot = {
  id: string
  /** Absolute timestamps. Render them in DailySchedule.timezone. */
  start_at: string
  end_at: string
  explanation: string | null
} & (
  | { kind: 'task'; task_id: string; is_pinned: boolean }
  | { kind: 'break' | 'lunch' | 'rest'; task_id: null; is_pinned: false }
)

export type DailySchedule = {
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
