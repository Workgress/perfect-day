import { apiError, apiProblem } from '@/shared/api/errors'
import { HttpError } from '@/shared/api/http'
import { plannerExplanation, plannerMessage } from './plannerText'

describe('planner text presentation', () => {
  it('formats a pinned placement from the task panel screenshot', () => {
    expect(
      plannerExplanation(
        '13:00 +0500–14:00 +0500. Начало закреплено пользователем. Длительность: 60 мин.',
      ),
    ).toBe('Время закреплено вами.')
  })

  it.each(['задачей', 'перерывом', 'отдыхом', 'обедом'])(
    'keeps the occupied interval and its cause: %s',
    (kind) => {
      const message = `Интервал занят ${kind} с 14:45 +0500 до 15:45 +0500.`
      const error = new HttpError(409, {
        error: {
          code: 'INTERVAL_OCCUPIED',
          message,
          details: { kind },
        },
      })
      expect(apiError(error)).toBe(`Интервал занят ${kind} с 14:45 до 15:45.`)
      expect(apiProblem(error)).toMatchObject({
        code: 'INTERVAL_OCCUPIED',
        message,
        details: { kind },
      })
    },
  )

  it('retains the server reasons, negative measurements, preference and deadline', () => {
    const result = plannerExplanation(
      '14:45 +0500–15:45 +0500. Время выбрано по оценке энергии и ограничениям расписания. Интеллектуальный биоритм: среднее за интервал -6.5%. Среднее значение суточного профиля: 78.1% (хронотип: жаворонок). Учтено предпочтительное время начала. Длительность: 60 мин. Дедлайн: 26.11.2026 17:00 +0500.',
    )
    expect(result).toBe(
      'Учтены биоритмы, режим дня и свободное время. Интеллектуальный биоритм за это время: −6,5 %. Учтено предпочтительное время начала. Дедлайн: 26.11.2026 17:00.',
    )
    expect(result).not.toMatch(/Пик|Подъём|Спад/)
  })

  it('keeps distinct UTC offsets when local times repeat during DST', () => {
    expect(
      plannerExplanation(
        '02:30 +0200–02:30 +0100. Начало закреплено пользователем. Длительность: 60 мин.',
      ),
    ).toBe('02:30 (UTC+02:00)–02:30 (UTC+01:00). Время закреплено вами.')
    expect(plannerMessage('Интервал занят с 02:00 +0200 до 02:30 +0100.')).toBe(
      'Интервал занят с 02:00 (UTC+02:00) до 02:30 (UTC+01:00).',
    )
  })

  it.each([
    'Предварительно: интеллектуальное окно.',
    'Задача выполнена; сохранён её исходный интервал.',
    'Задача начата пользователем; время начала зафиксировано.',
    'Вторая волна концентрации после обеда',
  ])('preserves backend and local copy and can format it repeatedly: %s', (text) => {
    expect(plannerExplanation(text)).toBe(text)
    expect(plannerExplanation(plannerExplanation(text))).toBe(text)
  })
})
