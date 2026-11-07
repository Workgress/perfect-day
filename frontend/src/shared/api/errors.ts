import { HttpError } from './http'

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
      return [body.error.message, ...details].join('. ')
    }
    if (error.status === 404) return 'Эта функция пока недоступна на сервере.'
    if (error.status >= 500) return 'Сервис временно недоступен. Попробуйте ещё раз.'
  }
  return error instanceof TypeError
    ? 'Нет связи с сервером. Проверьте подключение и повторите попытку.'
    : error instanceof Error
      ? error.message
      : 'Не удалось выполнить запрос.'
}
