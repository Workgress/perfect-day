import type { OnboardingDraft, OnboardingRequest } from '@/shared/model/onboarding'
import type { PlanPreview } from '@/shared/model/plan'
import { dayWindows } from './chronotype'
import { formatTime } from './model'

export function localPlanPreview(
  body: OnboardingRequest,
  draft: OnboardingDraft,
  timezone: string,
): PlanPreview {
  const windows = dayWindows(draft.chronotype, draft.workStart, draft.workEnd)
    .filter((window) => window.type !== 'rest')
    .map((window) => ({ ...window, available: window.start }))
  const slots: PlanPreview['slots'] = []
  const unscheduled: number[] = []
  body.tasks.forEach((task, task_index) => {
    const preferred = windows.filter((window) => window.type === task.type)
    if (task.type === 'routine') preferred.reverse()
    const window = [...preferred, ...windows].find(
      (window) => window.end - window.available >= task.duration_min,
    )
    if (!window) {
      unscheduled.push(task_index)
      return
    }
    const start = window.available
    window.available += task.duration_min
    slots.push({
      task_index,
      start_time: `${formatTime(start)}:00`,
      end_time: `${formatTime(window.available)}:00`,
      explanation: `Предварительно: ${window.label.toLocaleLowerCase('ru')}.`,
    })
  })
  slots.sort((a, b) => a.start_time.localeCompare(b.start_time))
  return {
    planned_date: body.planned_date,
    timezone,
    slots,
    unscheduled_task_indexes: unscheduled,
    local: true,
  }
}
