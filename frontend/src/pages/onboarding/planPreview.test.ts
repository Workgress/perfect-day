import { EMPTY_ONBOARDING } from '@/shared/model/onboarding'
import { localPlanPreview } from './planPreview'

const body = {
  planned_date: '2026-11-06',
  tasks: [
    { title: 'Экзамен', type: 'intellectual' as const, duration_min: 90 },
    { title: 'Курсовая', type: 'intellectual' as const, duration_min: 90 },
    { title: 'Тренировка', type: 'physical' as const, duration_min: 60 },
    { title: 'Литература', type: 'routine' as const, duration_min: 60 },
  ],
}

describe('local plan preview', () => {
  it.each([
    ['lark', '08:00', '18:00', '10:00:00', '13:00:00', '15:00:00', '16:00:00'],
    ['dove', '09:00', '19:00', '11:00:00', '14:00:00', '16:00:00', '17:00:00'],
    ['owl', '12:00', '22:00', '14:00:00', '17:00:00', '19:00:00', '20:00:00'],
  ] as const)(
    'uses %s windows without scheduling lunch or the break',
    (chronotype, workStart, workEnd, ...times) => {
      const original = structuredClone(body)
      const plan = localPlanPreview(
        body,
        { ...EMPTY_ONBOARDING, chronotype, workStart, workEnd },
        'UTC',
      )
      expect(plan.slots.map((slot) => slot.start_time)).toEqual(times)
      expect(plan.slots.map((slot) => slot.task_index)).toEqual([0, 1, 2, 3])
      expect(plan.unscheduled_task_indexes).toEqual([])
      expect(plan.local).toBe(true)
      expect(plan.slots.every((slot) => slot.explanation.startsWith('Предварительно:'))).toBe(true)
      expect(JSON.stringify(plan)).not.toContain('%')
      expect(body).toEqual(original)
    },
  )

  it('reports tasks that do not fit instead of overlapping or silently omitting them', () => {
    const plan = localPlanPreview(
      body,
      { ...EMPTY_ONBOARDING, workStart: '10:00', workEnd: '11:30' },
      'UTC',
    )
    expect(plan.slots).toHaveLength(1)
    expect(plan.slots[0]).toMatchObject({
      task_index: 0,
      start_time: '10:00:00',
      end_time: '11:30:00',
    })
    expect(plan.unscheduled_task_indexes).toEqual([1, 2, 3])
  })
})
