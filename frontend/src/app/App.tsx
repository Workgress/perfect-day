import { RouterProvider } from 'react-router'
import { router } from '@/app/router/router'
import { SessionProvider } from '@/app/session/SessionProvider'

export function App() {
  return (
    <SessionProvider>
      <RouterProvider router={router} />
    </SessionProvider>
  )
}
