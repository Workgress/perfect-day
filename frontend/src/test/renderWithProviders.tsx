import type { ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { createQueryClient } from '@/shared/api/queryClient'

export function renderWithProviders(ui: ReactNode) {
  const queryClient = createQueryClient()
  queryClient.setDefaultOptions({ queries: { retry: false } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}
