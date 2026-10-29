import { RouterProvider } from 'react-router'
import { router } from '@/app/router/router'
import { setupHttp } from '@/app/setupHttp'
import { createQueryClient } from '@/shared/api/queryClient'
import { AppProviders } from './AppProviders'

setupHttp()

const queryClient = createQueryClient()

export function App() {
  return (
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>
  )
}
