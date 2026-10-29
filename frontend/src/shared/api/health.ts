import { queryOptions } from '@tanstack/react-query'
import { http } from './http'

export type HealthResponse = {
  status: 'ok'
}

export const healthQuery = queryOptions({
  queryKey: ['health'],
  queryFn: ({ signal }) => http<HealthResponse>('/health', { signal }),
  refetchInterval: 60_000,
  retry: false,
})
