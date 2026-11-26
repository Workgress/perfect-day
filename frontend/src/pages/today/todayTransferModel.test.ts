import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import type { DailySchedule } from '@/shared/model/schedule'
import { planningDetails, savedFixture } from '@/test/planningDetails'
import { transferProposal } from './todayTransferModel'

const day = DAILY_SCHEDULE_FIXTURES.normal
const now = Date.parse('2026-11-11T04:42:00Z')
function advised(value: DailySchedule, index = 5) {
  return {
    ...value,
    planning: planningDetails(savedFixture(day), {
      recommendations: [
        {
          task_id: day.tasks[index].id,
          from_date: day.date,
          to_date: '2026-11-16',
          reason_code: 'DAY_OVERLOADED',
          explanation: 'На 16 ноября задача помещается целиком.',
        },
      ],
    }),
  }
}

describe('server move recommendations', () => {
  it('never invents a recommendation when the server supplied none', () => {
    expect(transferProposal(day, now)).toBeNull()
  })
  it('uses the server target date and explanation, including for routine tasks', () => {
    const proposal = transferProposal(advised(day), now)!
    expect(proposal.task.id).toBe(day.tasks[5].id)
    expect(proposal.date).toBe('2026-11-16')
    expect(proposal.released).toBe(60)
    expect(proposal.explanation).toBe('На 16 ноября задача помещается целиком.')
  })
  it.each(['pending', 'scheduled'] as const)('ignores already moved tasks (%s)', (status) => {
    const tasks = day.tasks.map((task, index) =>
      index === 5 ? { ...task, planned_date: '2026-11-12', status } : task,
    )
    expect(transferProposal(advised({ ...day, tasks }), now)).toBeNull()
  })
  it.each([
    { is_pinned: true },
    { is_date_locked: true },
    { actual_start: '2026-11-11T04:42:00Z' },
    { status: 'done' as const },
    { status: 'skipped' as const },
  ])('does not offer a protected or inactive task: %j', (fields) => {
    const tasks = day.tasks.map((task, index) => (index === 5 ? { ...task, ...fields } : task))
    expect(transferProposal(advised({ ...day, tasks }), now)).toBeNull()
  })
  it('does not offer a scheduled interval whose start has passed', () => {
    expect(transferProposal(advised(day), Date.parse('2026-11-11T11:00:00Z'))).toBeNull()
  })
  it('does not promise freed time for a task without an interval', () => {
    const tasks = day.tasks.map((task, index) =>
      index === 5 ? { ...task, status: 'pending' as const } : task,
    )
    expect(transferProposal(advised({ ...day, tasks, slots: [] }), now)?.released).toBe(0)
  })
})
