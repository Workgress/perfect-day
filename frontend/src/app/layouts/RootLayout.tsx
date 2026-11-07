import { Outlet, ScrollRestoration } from 'react-router'
import { SessionGate } from '@/app/SessionGate'

export function RootLayout() {
  return (
    <>
      <SessionGate>
        <Outlet />
      </SessionGate>
      <ScrollRestoration />
    </>
  )
}
