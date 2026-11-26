import type { DailySchedule, SavedSchedule, SchedulePlanningDetails } from '@/shared/model/schedule'

export function savedFixture(day: DailySchedule): SavedSchedule {
  return {
    id: day.schedule!.id,
    planned_date: day.date,
    timezone: day.timezone,
    version: day.schedule!.version,
    algorithm_version: 'test',
    generated_at: `${day.date}T04:00:00Z`,
    slots: day.slots.map((slot) => ({ ...slot, reason_codes: [] })),
    unscheduled: day.unscheduled_task_ids.map((task_id) => ({
      task_id,
      reason_codes: ['NO_FEASIBLE_INTERVAL'],
    })),
    warnings: [],
    moves: [],
    metrics: {
      requested_min: 420,
      planned_min: 420,
      capacity_min: 600,
      high_intensity_min: 180,
      critical_level: 0,
      load_factor: 1,
      moved_min: 0,
    },
  }
}

export function planningDetails(
  schedule: SavedSchedule,
  overrides: Partial<Omit<SchedulePlanningDetails, 'schedule'>> = {},
): SchedulePlanningDetails {
  return {
    schedule,
    recommendations: [],
    placement_explanations: schedule.slots
      .filter((slot) => slot.kind === 'task')
      .map((slot) => ({
        task_id: slot.task_id!,
        planned_date: schedule.planned_date,
        start_at: slot.start_at,
        end_at: slot.end_at,
        preservation: slot.is_pinned ? 'pinned' : null,
        reason_codes: slot.reason_codes.length ? slot.reason_codes : ['ENERGY_RANKED'],
        explanation: slot.explanation ?? 'Время выбрано планировщиком.',
      })),
    unscheduled_explanations: schedule.unscheduled.map((item) => ({
      task_id: item.task_id,
      planned_date: schedule.planned_date,
      reason_codes: item.reason_codes.length ? item.reason_codes : ['NO_FEASIBLE_INTERVAL'],
      explanation: 'Не найдено непрерывного окна нужной длительности. Дата задачи сохранена.',
    })),
    ...overrides,
  }
}
