import type { ReactNode } from 'react'
import { useHref, useLinkClickHandler, useMatch, useResolvedPath } from 'react-router'
import { NavItem } from '@/shared/ui/nav-item/NavItem'

type SidebarLinkProps = {
  to: string
  className?: string
  children: ReactNode
}

export function SidebarLink({ to, className, children }: SidebarLinkProps) {
  const href = useHref(to)
  const handleClick = useLinkClickHandler(to)
  const { pathname } = useResolvedPath(to)
  const isActive = useMatch({ path: pathname, end: false }) !== null

  return (
    <NavItem
      href={href}
      onClick={handleClick}
      aria-current={isActive ? 'page' : undefined}
      className={className}
    >
      {children}
    </NavItem>
  )
}
