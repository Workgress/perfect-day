/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { SavedSchedule } from '@/shared/model/schedule'
import { HttpError } from './http'
import { apiProblem } from './errors'
import { getSchedule, getScheduleDetails, replanSchedule } from './schedule'
import { planningDetails } from '@/test/planningDetails'

const fixtures = JSON.parse(
  readFileSync(
    resolve(
      dirname(fileURLToPath(import.meta.url)),
      '../../../../contracts/fixtures/schedule_read_examples.json',
    ),
    'utf8',
  ),
) as {
  day_with_tasks: SavedSchedule
  empty_day: SavedSchedule
  missing_schedule: unknown
  onboarding_required: unknown
  incomplete_schedule: unknown
}

describe('saved schedule API contract', () => {
  it('reads explanations and recommendations together from the details endpoint', async () => {
    const details = planningDetails(fixtures.day_with_tasks)
    const request = vi.fn<typeof fetch>(async () => Response.json(details))
    vi.stubGlobal('fetch', request)
    expect(await getScheduleDetails(details.schedule.planned_date)).toEqual(details)
    expect(new URL(String(request.mock.calls[0][0])).pathname).toMatch(/\/schedule\/details$/)
    expect(request.mock.calls[0][1]?.cache).toBe('no-store')
  })

  it.each([
    'missing_explanations',
    'wrong_date',
    'unknown_task',
    'same_target',
    'duplicate_placement',
    'wrong_interval',
  ])('rejects inconsistent planner details: %s', async (error) => {
    const details = planningDetails(fixtures.day_with_tasks)
    const task = details.placement_explanations[0]
    if (error === 'missing_explanations') details.placement_explanations = []
    if (error === 'wrong_date') task.planned_date = '2026-11-01'
    if (error === 'duplicate_placement') details.placement_explanations.push({ ...task })
    if (error === 'wrong_interval') task.end_at = task.start_at
    if (error === 'unknown_task' || error === 'same_target')
      details.recommendations = [
        {
          task_id: error === 'unknown_task' ? '10000000-0000-4000-8000-000000000099' : task.task_id,
          from_date: details.schedule.planned_date,
          to_date: error === 'same_target' ? details.schedule.planned_date : '2026-12-01',
          reason_code: 'DAY_OVERLOADED',
          explanation: 'Проверенное предложение переноса.',
        },
      ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json(details)),
    )
    await expect(getScheduleDetails(details.schedule.planned_date)).rejects.toThrow(
      'некорректные данные',
    )
  })
  it.each([fixtures.day_with_tasks, fixtures.empty_day])(
    'reads a backend contract example: $planned_date',
    async (saved) => {
      const request = vi.fn<typeof fetch>(async () => Response.json(saved))
      vi.stubGlobal('fetch', request)
      const controller = new AbortController()
      expect(await getSchedule(saved.planned_date, controller.signal)).toEqual(saved)
      expect(new URL(String(request.mock.calls[0][0])).searchParams.get('date')).toBe(
        saved.planned_date,
      )
      expect(request.mock.calls[0][1]).toMatchObject({
        cache: 'no-store',
        signal: controller.signal,
      })
    },
  )

  it.each([
    [404, fixtures.missing_schedule, 'SCHEDULE_NOT_FOUND'],
    [409, fixtures.onboarding_required, 'ONBOARDING_REQUIRED'],
    [409, fixtures.incomplete_schedule, 'SCHEDULE_RESULT_INCOMPLETE'],
  ] as const)('preserves %s as a distinct error, not an empty day', async (status, body, code) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json(body, { status })),
    )
    const error = await getSchedule('2026-11-19').catch((error) => error)
    expect(error).toBeInstanceOf(HttpError)
    expect(apiProblem(error)?.code).toBe(code)
  })

  it.each(['2026-02-30', '2026-11-19T00:00:00Z', '0000-01-01'])(
    'rejects invalid dates before sending %s',
    async (date) => {
      await expect(getSchedule(date)).rejects.toThrow(RangeError)
      expect(fetch).not.toHaveBeenCalled()
    },
  )

  it.each([
    null,
    { ...fixtures.day_with_tasks, timezone: 'invalid/zone' },
    { ...fixtures.day_with_tasks, metrics: null },
    { ...fixtures.day_with_tasks, version: 0 },
    { ...fixtures.day_with_tasks, slots: [{ ...fixtures.day_with_tasks.slots[0], task_id: null }] },
    {
      ...fixtures.day_with_tasks,
      slots: [
        { ...fixtures.day_with_tasks.slots[0], end_at: fixtures.day_with_tasks.slots[0].start_at },
      ],
    },
    {
      ...fixtures.day_with_tasks,
      slots: [{ ...fixtures.day_with_tasks.slots[0], reason_codes: undefined }],
    },
  ])('rejects malformed saved data %#', async (body) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json(body)),
    )
    await expect(getSchedule('2026-11-18')).rejects.toThrow('некорректные данные')
  })

  it('rejects a valid response belonging to a different day', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json(fixtures.day_with_tasks)),
    )
    await expect(getSchedule('2026-11-19')).rejects.toThrow('другую дату')
  })

  it.each([
    { ...fixtures.day_with_tasks, planned_date: '2026-11-19' },
    { ...fixtures.day_with_tasks, version: 1 },
    { ...fixtures.day_with_tasks, slots: null },
  ])('rejects an unrelated, stale or malformed replan result %#', async (saved) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json({ schedule: saved })),
    )
    await expect(replanSchedule('2026-11-18', 1)).rejects.toThrow()
  })

  it.each([-1, 1.5, NaN])('does not submit an invalid replan version %s', async (version) => {
    await expect(replanSchedule('2026-11-18', version)).rejects.toThrow(RangeError)
    expect(fetch).not.toHaveBeenCalled()
  })
})
