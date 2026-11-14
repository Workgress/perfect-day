/// <reference types="node" />

import { previewPlan } from './plan'
import { HttpError } from './http'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { PlanPreview, PlanPreviewRequest } from '@/shared/model/plan'

const body = {
  planned_date: '2026-11-06',
  tasks: [{ title: 'Экзамен', type: 'intellectual' as const, duration_min: 90 }],
}
const response = {
  planned_date: body.planned_date,
  timezone: 'Asia/Yekaterinburg',
  slots: [
    { task_index: 0, start_time: '10:00:00', end_time: '11:30:00', explanation: 'Утреннее окно' },
  ],
  unscheduled_task_indexes: [],
}

describe('plan preview API', () => {
  const fixtureJson = readFileSync(
    resolve(
      dirname(fileURLToPath(import.meta.url)),
      '../../../../contracts/fixtures/planner_cases.json',
    ),
    'utf8',
  )
  const fixtures = JSON.parse(fixtureJson) as {
    http_preview_cases: { id: string; request: PlanPreviewRequest; expected: PlanPreview }[]
  }

  it.each(fixtures.http_preview_cases)('accepts the backend fixture $id', async (testCase) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json(testCase.expected)),
    )
    expect(await previewPlan(testCase.request)).toEqual(testCase.expected)
  })

  it('posts the draft without completing onboarding and accepts server explanations', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json(response))
    vi.stubGlobal('fetch', fetchMock)
    expect(await previewPlan(body)).toEqual(response)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/onboarding/preview')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'POST', body: JSON.stringify(body) })
  })

  it.each([
    { ...response, slots: [] },
    { ...response, unscheduled_task_indexes: [0] },
    { ...response, slots: [{ ...response.slots[0], task_index: 1 }] },
    { ...response, slots: [{ ...response.slots[0], end_time: '10:30:00' }] },
    { ...response, slots: [{ ...response.slots[0], explanation: '' }] },
  ])('rejects inconsistent plan data %#', async (value) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json(value)),
    )
    await expect(previewPlan(body)).rejects.toThrow()
  })

  it('preserves infrastructure errors for the UI instead of returning a fake success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json({ error: { code: 'PLANNER_UNAVAILABLE' } }, { status: 503 })),
    )
    await expect(previewPlan(body)).rejects.toBeInstanceOf(HttpError)
  })
})
