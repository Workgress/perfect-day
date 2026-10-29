import { lazy, Suspense, type ReactNode } from 'react'
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { ThemeSync } from '@/app/theme/ThemeSync'

const QueryDevtools = import.meta.env.DEV
  ? lazy(async () => ({
      default: (await import('@tanstack/react-query-devtools')).ReactQueryDevtools,
    }))
  : null

type AppProvidersProps = {
  queryClient: QueryClient
  children: ReactNode
}

export function AppProviders({ queryClient, children }: AppProvidersProps) {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeSync />
      {children}
      {QueryDevtools ? (
        <Suspense fallback={null}>
          <QueryDevtools buttonPosition="bottom-right" />
        </Suspense>
      ) : null}
    </QueryClientProvider>
  )
}
