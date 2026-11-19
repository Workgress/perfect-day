import { useSessionStore } from '@/stores/session'

export async function taskSessionRequest<T>(
  generation: number,
  request: (signal: AbortSignal) => Promise<T>,
  signal?: AbortSignal,
): Promise<T> {
  if (
    useSessionStore.getState().generation !== generation ||
    !useSessionStore.getState().accessToken
  )
    throw new DOMException('Сессия изменилась', 'AbortError')
  const controller = new AbortController()
  const abort = () => controller.abort()
  if (signal?.aborted) abort()
  signal?.addEventListener('abort', abort, { once: true })
  const unsubscribe = useSessionStore.subscribe((state) => {
    if (state.generation !== generation) abort()
  })
  try {
    const result = await request(controller.signal)
    if (controller.signal.aborted) throw new DOMException('Запрос отменён', 'AbortError')
    return result
  } finally {
    unsubscribe()
    signal?.removeEventListener('abort', abort)
  }
}
