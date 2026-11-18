import type {
  BiorhythmForecastRequest,
  BiorhythmRangeRequest,
  BiorhythmRequest,
  BiorhythmSnapshotRequest,
} from '@/shared/model/biorhythm'
import { http } from './http'
import {
  invalidBiorhythmResponse,
  isBiorhythmTimestamp,
  readBiorhythmCriticalDays,
  readBiorhythmSeries,
  readBiorhythmSnapshot,
  validateBiorhythmRange,
} from './biorhythmValidation'

export async function getBiorhythmSnapshot(
  request: BiorhythmSnapshotRequest = {},
  signal?: AbortSignal,
) {
  if (request.at !== undefined && !isBiorhythmTimestamp(request.at))
    throw new RangeError('Укажите момент ISO 8601 с датой, временем и UTC-смещением.')
  const result = readBiorhythmSnapshot(
    await http<unknown>('/biorhythms/now', {
      query: { at: request.at },
      signal,
      cache: 'no-store',
    }),
  )
  if (request.at !== undefined && Date.parse(result.at) !== Date.parse(request.at))
    return invalidBiorhythmResponse()
  return result
}

export async function getBiorhythmSeries(request: BiorhythmRequest, signal?: AbortSignal) {
  validateBiorhythmRange(request.from, request.to)
  const step = request.step ?? 'day'
  if (step !== 'day' && step !== 'hour') throw new RangeError('Выберите шаг day или hour.')
  const result = readBiorhythmSeries(
    await http<unknown>('/biorhythms', {
      query: { from: request.from, to: request.to, step },
      signal,
      cache: 'no-store',
    }),
  )
  if (
    result.start !== request.from ||
    result.end !== request.to ||
    result.step !== step ||
    result.period !== null
  )
    return invalidBiorhythmResponse()
  return result
}

export async function getBiorhythmForecast(
  request: BiorhythmForecastRequest,
  signal?: AbortSignal,
) {
  if (!['day', 'week', 'month'].includes(request.period))
    throw new RangeError('Выберите период day, week или month.')
  const result = readBiorhythmSeries(
    await http<unknown>('/biorhythms/forecast', {
      query: { period: request.period },
      signal,
      cache: 'no-store',
    }),
  )
  if (
    result.period !== request.period ||
    result.step !== (request.period === 'day' ? 'hour' : 'day')
  )
    return invalidBiorhythmResponse()
  return result
}

export async function getBiorhythmCriticalDays(
  request: BiorhythmRangeRequest,
  signal?: AbortSignal,
) {
  validateBiorhythmRange(request.from, request.to)
  const result = readBiorhythmCriticalDays(
    await http<unknown>('/biorhythms/critical-days', {
      query: { from: request.from, to: request.to },
      signal,
      cache: 'no-store',
    }),
  )
  if (result.start !== request.from || result.end !== request.to) return invalidBiorhythmResponse()
  return result
}
