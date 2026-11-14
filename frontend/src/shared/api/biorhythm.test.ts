import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { useSessionStore } from '@/stores/session'
import {
  BIORHYTHM_FIXTURES,
  BIORHYTHM_CRITICAL_DAYS_FIXTURE,
  BIORHYTHM_SNAPSHOT_FIXTURE,
} from '@/shared/fixtures/biorhythms'
import { toBiorhythmChartPoints } from '@/shared/lib/biorhythm'
import type { BiorhythmPeriod, BiorhythmSeries, BiorhythmSnapshot } from '@/shared/model/biorhythm'
import {
  getBiorhythmCriticalDays,
  getBiorhythmForecast,
  getBiorhythmSeries,
  getBiorhythmSnapshot,
} from './biorhythm'
import { HttpError } from './http'
import {
  readBiorhythmCriticalDays,
  readBiorhythmSeries,
  readBiorhythmSnapshot,
} from './biorhythmValidation'

type Example = {
  request: { path: string; query: Record<string, string> }
  response: { body: unknown }
}
const examples = (
  JSON.parse(
    readFileSync(
      resolve(
        dirname(fileURLToPath(import.meta.url)),
        '../../../../contracts/fixtures/biorhythm_api_examples.json',
      ),
      'utf8',
    ),
  ) as { examples: Record<'now' | 'series' | 'critical_days' | 'forecast', Example> }
).examples

function respond(body: unknown, status = 200) {
  const fetchMock = vi.fn<typeof fetch>(async () => Response.json(body, { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('biorhythm API', () => {
  beforeEach(() => {
    useSessionStore.getState().signIn({ accessToken: 'bio-token' })
  })

  it.each([
    ['now', () => getBiorhythmSnapshot({ at: examples.now.request.query.at })],
    [
      'series',
      () =>
        getBiorhythmSeries({
          from: examples.series.request.query.from,
          to: examples.series.request.query.to,
        }),
    ],
    [
      'critical_days',
      () =>
        getBiorhythmCriticalDays({
          from: examples.critical_days.request.query.from,
          to: examples.critical_days.request.query.to,
        }),
    ],
    [
      'forecast',
      () =>
        getBiorhythmForecast({ period: examples.forecast.request.query.period as BiorhythmPeriod }),
    ],
  ] as const)(
    'reads the published backend example %s without recalculating values',
    async (name, request) => {
      const example = examples[name]
      const fetchMock = respond(example.response.body)
      expect(await request()).toEqual(example.response.body)
      const [input, init] = fetchMock.mock.calls[0]
      const url = new URL(String(input))
      expect(url.pathname).toBe(example.request.path)
      expect(Object.fromEntries(url.searchParams)).toEqual(example.request.query)
      expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer bio-token')
      expect(init).toMatchObject({ credentials: 'include', cache: 'no-store' })
    },
  )

  it('encodes a positive UTC offset and compares absolute instants', async () => {
    const fetchMock = respond(examples.now.response.body)
    await getBiorhythmSnapshot({ at: '2026-11-08T15:00:00+05:00' })
    expect(String(fetchMock.mock.calls[0][0])).toContain('%2B05%3A00')
    expect(new URL(String(fetchMock.mock.calls[0][0])).searchParams.get('at')).toBe(
      '2026-11-08T15:00:00+05:00',
    )
  })

  it('omits at when requesting the current server moment', async () => {
    const fetchMock = respond(examples.now.response.body)
    await getBiorhythmSnapshot()
    expect(new URL(String(fetchMock.mock.calls[0][0])).search).toBe('')
  })

  it.each([
    { from: '2026-11-10', to: '2026-11-09' },
    { from: '2026-11-01', to: '2027-01-02' },
    { from: '2026-02-30', to: '2026-03-01' },
    { from: '2026-11-08T00:00:00Z', to: '2026-11-09' },
    { from: '0000-01-01', to: '0000-01-02' },
  ])('rejects an invalid inclusive range before sending a request: $from / $to', async (range) => {
    const fetchMock = respond({})
    await expect(getBiorhythmSeries(range)).rejects.toBeInstanceOf(RangeError)
    await expect(getBiorhythmCriticalDays(range)).rejects.toBeInstanceOf(RangeError)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('accepts exactly 62 days inclusive', async () => {
    const fetchMock = respond(BIORHYTHM_FIXTURES.range)
    await expect(getBiorhythmSeries({ from: '2026-11-01', to: '2027-01-01' })).resolves.toEqual(
      BIORHYTHM_FIXTURES.range,
    )
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it.each(['2026-11-08', '2026-11-08T10:00:00', '2026-02-30T10:00:00Z'])(
    'requires an explicit timestamp offset: %s',
    async (at) => {
      const fetchMock = respond({})
      await expect(getBiorhythmSnapshot({ at })).rejects.toBeInstanceOf(RangeError)
      expect(fetchMock).not.toHaveBeenCalled()
    },
  )

  it('forwards the abort signal for period changes', async () => {
    const controller = new AbortController()
    const fetchMock = respond(examples.forecast.response.body)
    await getBiorhythmForecast({ period: 'week' }, controller.signal)
    expect(fetchMock.mock.calls[0][1]?.signal).toBe(controller.signal)
  })

  it('rejects a response for a different requested range or step', async () => {
    respond(examples.series.response.body)
    await expect(getBiorhythmSeries({ from: '2026-11-08', to: '2026-11-10' })).rejects.toThrow(
      'некорректные данные',
    )
    await expect(
      getBiorhythmSeries({ from: '2026-11-08', to: '2026-11-09', step: 'hour' }),
    ).rejects.toThrow('некорректные данные')
  })

  it('rejects a forecast for another period and a snapshot for another instant', async () => {
    respond(examples.forecast.response.body)
    await expect(getBiorhythmForecast({ period: 'month' })).rejects.toThrow('некорректные данные')
    respond(examples.now.response.body)
    await expect(getBiorhythmSnapshot({ at: '2026-11-08T11:00:00Z' })).rejects.toThrow(
      'некорректные данные',
    )
  })

  it.each([401, 403, 409, 422, 503])(
    'preserves HTTP %s and its error details without substituting demo data',
    async (status) => {
      const body = {
        error: {
          code: status === 409 ? 'ONBOARDING_REQUIRED' : 'VALIDATION_ERROR',
          message: 'Ошибка запроса',
          details: { fields: [{ field: 'query.from', code: 'BEFORE_BIRTH' }] },
        },
      }
      respond(body, status)
      const error: unknown = await getBiorhythmSeries({
        from: '2026-11-08',
        to: '2026-11-09',
      }).catch((reason: unknown) => reason)
      expect(error).toBeInstanceOf(HttpError)
      expect(error).toMatchObject({ status, body })
    },
  )

  it('preserves connection failures and aborted requests', async () => {
    for (const error of [
      new TypeError('Failed to fetch'),
      new DOMException('Aborted', 'AbortError'),
    ]) {
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => {
          throw error
        }),
      )
      await expect(getBiorhythmForecast({ period: 'week' })).rejects.toBe(error)
    }
  })
})

function backendSnapshot(): BiorhythmSnapshot {
  return structuredClone(examples.now.response.body) as BiorhythmSnapshot
}

function backendSeries(): BiorhythmSeries {
  return structuredClone(examples.series.response.body) as BiorhythmSeries
}

describe('biorhythm response models and chart adapter', () => {
  const snapshot = backendSnapshot()
  const series = backendSeries()

  it.each([
    null,
    [],
    { ...snapshot, timezone: 'Invalid/Timezone' },
    { ...snapshot, algorithm_version: '' },
    { ...snapshot, at: '2026-11-08T10:00:00' },
    { ...snapshot, date: '2026-11-09' },
    { ...snapshot, cycles: { ...snapshot.cycles, physical: undefined } },
    {
      ...snapshot,
      cycles: { ...snapshot.cycles, physical: { ...snapshot.cycles.physical, value: 41.9 } },
    },
    {
      ...snapshot,
      cycles: { ...snapshot.cycles, physical: { ...snapshot.cycles.physical, percent: 4190 } },
    },
    {
      ...snapshot,
      cycles: { ...snapshot.cycles, physical: { ...snapshot.cycles.physical, percent: NaN } },
    },
    {
      ...snapshot,
      cycles: { ...snapshot.cycles, physical: { ...snapshot.cycles.physical, phase: 'falling' } },
    },
    {
      ...snapshot,
      cycles: { ...snapshot.cycles, physical: { ...snapshot.cycles.physical, trend: undefined } },
    },
    { ...snapshot, critical: { level: 1, kind: 'none', crossings: [] } },
    {
      ...snapshot,
      critical: {
        level: 1,
        kind: 'single',
        crossings: [{ cycle: 'physical', at: '2026-11-09T00:00:00Z' }],
      },
    },
  ])('rejects a malformed snapshot %#', (value) => {
    expect(() => readBiorhythmSnapshot(value)).toThrow('некорректные данные')
  })

  it.each([
    { ...series, points: [] },
    { ...series, points: [series.points[0]] },
    { ...series, points: [...series.points].reverse() },
    { ...series, points: [series.points[0], series.points[0], series.points[1]] },
    { ...series, step: 'minute' },
    { ...series, period: undefined },
  ])('rejects incomplete or inconsistent series %#', (value) => {
    expect(() => readBiorhythmSeries(value)).toThrow('некорректные данные')
  })

  it('uses the response timezone to validate local dates instead of the UTC date or browser timezone', () => {
    const value = {
      ...backendSnapshot(),
      timezone: 'Asia/Yekaterinburg',
      at: '2026-11-07T22:00:00Z',
    }
    expect(readBiorhythmSnapshot(value).date).toBe('2026-11-08')
    expect(() => readBiorhythmSnapshot({ ...value, date: '2026-11-07' })).toThrow()
  })

  it.each([
    { date: '2026-03-29', start: '2026-03-28T23:00:00Z', hours: 23 },
    { date: '2026-10-25', start: '2026-10-24T22:00:00Z', hours: 25 },
  ])('preserves $hours hourly points on the DST date $date', ({ date, start, hours }) => {
    const value: BiorhythmSeries = {
      ...backendSeries(),
      timezone: 'Europe/Berlin',
      start: date,
      end: date,
      step: 'hour',
      period: 'day',
      points: Array.from({ length: hours }, (_, index) => ({
        ...backendSeries().points[0],
        date,
        at: new Date(Date.parse(start) + index * 3_600_000).toISOString(),
      })),
    }
    const chart = toBiorhythmChartPoints(readBiorhythmSeries(value))
    expect(chart).toHaveLength(hours)
    expect(new Set(chart.map((point) => point.timestamp)).size).toBe(hours)
    expect(chart.every((point) => point.date === date)).toBe(true)
  })

  it('keeps hourly timestamps in a timezone with a fractional UTC offset', () => {
    const value: BiorhythmSeries = {
      ...backendSeries(),
      timezone: 'Asia/Kathmandu',
      start: '2026-11-08',
      end: '2026-11-08',
      step: 'hour',
      period: 'day',
      points: Array.from({ length: 24 }, (_, index) => ({
        ...backendSeries().points[0],
        at: new Date(Date.parse('2026-11-07T18:15:00Z') + index * 3_600_000).toISOString(),
      })),
    }
    expect(toBiorhythmChartPoints(readBiorhythmSeries(value))[0].timestamp).toBe(
      Date.parse('2026-11-07T18:15:00Z'),
    )
  })

  it('takes chart percentages directly from the server and does not mutate the source', () => {
    const value = backendSeries()
    const before = structuredClone(value)
    const chart = toBiorhythmChartPoints(readBiorhythmSeries(value))
    expect(chart[0]).toEqual({
      timestamp: Date.parse(value.points[0].at),
      date: value.points[0].date,
      physical: 39.8,
      emotional: 97.5,
      intellectual: 97.2,
    })
    expect(value).toEqual(before)
    expect(value.points[0].cycles.physical.value).toBe(0.398401089846)
  })

  it('accepts no critical days as a valid empty result', () => {
    expect(
      readBiorhythmCriticalDays({ ...BIORHYTHM_CRITICAL_DAYS_FIXTURE, days: [] }).days,
    ).toEqual([])
  })

  it('rejects duplicate critical dates and zero-level days in the filtered endpoint', () => {
    const value = structuredClone(examples.critical_days.response.body) as { days: unknown[] }
    expect(() =>
      readBiorhythmCriticalDays({ ...value, days: [value.days[0], value.days[0]] }),
    ).toThrow()
    expect(() =>
      readBiorhythmCriticalDays({
        ...BIORHYTHM_CRITICAL_DAYS_FIXTURE,
        days: [{ date: '2026-11-11', level: 0, kind: 'none', crossings: [] }],
      }),
    ).toThrow()
  })

  it('accepts zero readings and all three critical cycles', () => {
    const value = backendSnapshot()
    for (const cycle of ['physical', 'emotional', 'intellectual'] as const)
      value.cycles[cycle] = { value: 0, percent: 0, phase: 'rising', trend: 'up' }
    value.critical = {
      level: 3,
      kind: 'triple',
      crossings: (['physical', 'emotional', 'intellectual'] as const).map((cycle) => ({
        cycle,
        at: value.at,
      })),
    }
    expect(readBiorhythmSnapshot(value)).toEqual(value)
  })

  it('keeps every layout fixture in the same format as the API', () => {
    for (const fixture of Object.values(BIORHYTHM_FIXTURES))
      expect(readBiorhythmSeries(fixture)).toEqual(fixture)
    expect(readBiorhythmSnapshot(BIORHYTHM_SNAPSHOT_FIXTURE)).toEqual(BIORHYTHM_SNAPSHOT_FIXTURE)
    expect(readBiorhythmCriticalDays(BIORHYTHM_CRITICAL_DAYS_FIXTURE)).toEqual(
      BIORHYTHM_CRITICAL_DAYS_FIXTURE,
    )
  })
})
