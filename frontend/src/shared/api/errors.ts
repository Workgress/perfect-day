import { HttpError } from './http'
import { plannerMessage } from '@/shared/lib/plannerText'

export type ApiProblem = {
  code: string
  message: string
  details: Record<string, unknown>
}

/** Preserve error codes and field paths for conflict handling and form validation. */
export function apiProblem(error: unknown): ApiProblem | null {
  if (!(error instanceof HttpError) || typeof error.body !== 'object' || error.body === null)
    return null
  const problem = (error.body as { error?: unknown }).error
  if (typeof problem !== 'object' || problem === null) return null
  const { code, message, details } = problem as Record<string, unknown>
  if (typeof code !== 'string' || typeof message !== 'string') return null
  return {
    code,
    message,
    details:
      typeof details === 'object' && details !== null && !Array.isArray(details)
        ? (details as Record<string, unknown>)
        : {},
  }
}

export function apiError(error: unknown): string {
  if (error instanceof HttpError) {
    const body = error.body as {
      error?: { message?: unknown; details?: { fields?: { message?: unknown }[] } }
    } | null
    if (typeof body?.error?.message === 'string') {
      const fields = body.error.details?.fields
      const details = Array.isArray(fields)
        ? [
            ...new Set(
              fields
                .map((field) => field.message)
                .filter((message): message is string => typeof message === 'string'),
            ),
          ]
        : []
      return plannerMessage([body.error.message, ...details].join('. '))
    }
    if (error.status === 404) return 'Эта функция пока недоступна на сервере.'
    if (error.status >= 500) return 'Сервис временно недоступен. Попробуйте ещё раз.'
  }
  return error instanceof TypeError
    ? 'Нет связи с сервером. Проверьте подключение и повторите попытку.'
    : error instanceof Error
      ? plannerMessage(error.message)
      : 'Не удалось выполнить запрос.'
}
