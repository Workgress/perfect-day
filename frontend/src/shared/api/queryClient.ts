import { QueryClient } from '@tanstack/react-query'
import { HttpError } from './http'

const MAX_RETRIES = 2

function shouldRetry(failureCount: number, error: Error) {
  if (error instanceof HttpError && error.status >= 400 && error.status < 500) return false
  return failureCount < MAX_RETRIES
}

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        retry: shouldRetry,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
  })
}
