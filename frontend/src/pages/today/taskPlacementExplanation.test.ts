import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { taskPlacementExplanation } from './taskPlacementExplanation'

const day = DAILY_SCHEDULE_FIXTURES.normal
const task = day.tasks[2]
const slot = day.slots.find((item) => item.kind === 'task' && item.task_id === task.id)!

describe('readable task placement explanation', () => {
  it('uses the server explanation without inventing a phase or a deadline justification', () => {
    expect(
      taskPlacementExplanation(
        task,
        {
          ...slot,
          explanation:
            '10:00 +0500–11:30 +0500. Интеллектуальный биоритм: среднее за интервал 95%.',
        },
        day.timezone,
      ),
    ).toBe('Интеллектуальный биоритм за это время: 95 %.')
  })

  it('preserves negative interval means without assigning an unsupported phase', () => {
    const text = taskPlacementExplanation(
      task,
      {
        ...slot,
        explanation:
          '10:00 +0500–11:30 +0500. Интеллектуальный биоритм: среднее за интервал -44.6%.',
      },
      day.timezone,
    )
    expect(text).toBe('Интеллектуальный биоритм за это время: −44,6 %.')
    expect(text).not.toMatch(/Пик|Подъём|Спад|дедлайн/)
  })

  it('shows the real time and explains missing information when the server gives no reason', () => {
    expect(taskPlacementExplanation(task, { ...slot, explanation: null }, day.timezone)).toBe(
      'Задача запланирована на 10:00–11:30. Объяснение выбора времени пока недоступно.',
    )
  })

  it('recognizes a pinned interval when the saved explanation is missing', () => {
    expect(
      taskPlacementExplanation(task, { ...slot, is_pinned: true, explanation: null }, day.timezone),
    ).toBe('Время 10:00–11:30 закреплено вами.')
  })

  it('uses an unfamiliar backend explanation as supplied', () => {
    expect(
      taskPlacementExplanation(
        task,
        { ...slot, explanation: 'Учтён обязательный перерыв.' },
        day.timezone,
      ),
    ).toBe('Учтён обязательный перерыв.')
  })
})
