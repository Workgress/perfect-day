import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { taskPlacementExplanation } from './taskPlacementExplanation'

const day = DAILY_SCHEDULE_FIXTURES.normal
const task = { ...day.tasks[2], deadline: '2026-11-11T09:00:00Z' }
const slot = day.slots.find((item) => item.kind === 'task' && item.task_id === task.id)!

describe('readable task placement explanation', () => {
  it('formats a measured peak, actual local window and deadline', () => {
    expect(
      taskPlacementExplanation(
        task,
        {
          ...slot,
          explanation:
            '10:00 +0500–11:30 +0500. Интеллектуальный биоритм: среднее за интервал 95%.',
        },
        day.timezone,
        'lark',
      ),
    ).toBe(
      'Пик интеллектуального цикла (+95 %) и утреннее окно жаворонка 10:00–11:30. 90 минут помещаются до дедлайна.',
    )
  })

  it('describes the user’s negative interval mean as a decline rather than a peak', () => {
    const placed = {
      ...slot,
      start_at: '2026-11-11T09:45:00Z',
      end_at: '2026-11-11T10:45:00Z',
      explanation:
        '14:45 +0500–15:45 +0500. Время выбрано по оценке энергии и ограничениям расписания. Интеллектуальный биоритм: среднее за интервал -44.6%.',
    }
    expect(
      taskPlacementExplanation(
        { ...task, deadline: '2026-11-11T11:00:00Z' },
        placed,
        day.timezone,
        'lark',
      ),
    ).toBe(
      'Спад интеллектуального цикла (−44,6 %) и дневное окно жаворонка 14:45–15:45. 60 минут помещаются до дедлайна.',
    )
  })

  it('uses a neutral explanation without an invented percentage when measurements are unavailable', () => {
    const text = taskPlacementExplanation(
      { ...task, deadline: null },
      { ...slot, explanation: null },
      day.timezone,
      'owl',
    )
    expect(text).toBe(
      'Для интеллектуальной задачи выбрано утреннее окно совы 10:00–11:30. Длительность задачи — 90 минут.',
    )
  })

  it('does not claim an interval meets an earlier deadline', () => {
    const text = taskPlacementExplanation(
      { ...task, deadline: '2026-11-11T05:00:00Z' },
      slot,
      day.timezone,
      null,
    )
    expect(text).toContain('Окончание задачи позже дедлайна.')
    expect(text).not.toContain('помещаются до дедлайна')
  })

  it('recognizes a pinned interval instead of claiming the algorithm chose its time', () => {
    expect(
      taskPlacementExplanation(
        task,
        { ...slot, is_pinned: true, explanation: null },
        day.timezone,
        'lark',
      ),
    ).toContain('Время 10:00–11:30 закреплено вами.')
  })
})
