import { DAILY_SCHEDULE_FIXTURES } from '@/shared/fixtures/planning'
import { transferProposal } from './todayTransferModel'

const day = DAILY_SCHEDULE_FIXTURES.normal
const now = Date.parse('2026-11-11T04:42:00Z')

describe('load transfer candidates', () => {
  it.each(['pending', 'scheduled'] as const)(
    'excludes a task already moved to another date (%s), even with stale schedule references',
    (status) => {
      const task = { ...day.tasks[3], planned_date: '2026-11-12', status }
      expect(
        transferProposal({ ...day, tasks: [task], unscheduled_task_ids: [task.id] }, now),
      ).toBeNull()
    },
  )
  it('prefers a future non-routine task with low priority and reports its occupied time', () => {
    const tasks = day.tasks.map((task, index) =>
      index === 5 ? { ...task, type: 'creative' as const } : task,
    )
    const proposal = transferProposal({ ...day, tasks }, now)!
    expect(proposal.task.id).toBe(day.tasks[5].id)
    expect(proposal.date).toBe('2026-11-12')
    expect(proposal.released).toBe(60)
  })
  it('does not move pinned, completed, started or expired tasks', () => {
    const tasks = day.tasks.map((task) => ({ ...task, deadline: '2026-11-11T23:00:00Z' }))
    expect(transferProposal({ ...day, tasks }, now)).toBeNull()
    expect(transferProposal(day, Date.parse('2026-11-11T16:00:00Z'))).toBeNull()
    const pinned = {
      ...day.tasks[5],
      is_pinned: true as const,
      pinned_start: '2026-11-11T11:00:00Z',
    }
    expect(transferProposal({ ...day, tasks: [pinned] }, now)).toBeNull()
  })
  it('does not promise freed time for a task without an interval', () => {
    const task = { ...day.tasks[5], type: 'creative' as const, status: 'pending' as const }
    const proposal = transferProposal({ ...day, tasks: [task], slots: [] }, now)!
    expect(proposal.released).toBe(0)
    expect(proposal.task.id).toBe(task.id)
  })
  it('never proposes routine tasks, including an unplaced routine with the same title', () => {
    const routine = { ...day.tasks[5], title: 'д', status: 'pending' as const }
    const intellectual = {
      ...day.tasks[3],
      title: 'д',
      type: 'intellectual' as const,
      duration_min: 120,
      status: 'pending' as const,
    }
    expect(transferProposal({ ...day, tasks: [routine], slots: [] }, now)).toBeNull()
    const proposal = transferProposal({ ...day, tasks: [routine, intellectual], slots: [] }, now)!
    expect(proposal.task.id).toBe(intellectual.id)
    expect(proposal.task.duration_min).toBe(120)
  })
})
