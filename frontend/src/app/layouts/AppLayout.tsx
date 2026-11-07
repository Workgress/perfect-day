import type { ComponentType } from 'react'
import { Outlet } from 'react-router'
import { paths } from '@/app/router/paths'
import { LogoutButton } from '@/app/LogoutButton'
import type { IconProps } from '@/shared/ui/icon/createIcon'
import { ActivityIcon, CalendarIcon, SlidersIcon, SunIcon } from '@/shared/ui/icon/icons'
import { selectUserName, useSessionStore } from '@/stores/session'
import { ThemeToggle } from '@/app/theme/ThemeToggle'
import { ServerStatus } from './ServerStatus'
import { SidebarLink } from './SidebarLink'
import styles from './AppLayout.module.css'

const NAVIGATION: readonly { to: string; label: string; Icon: ComponentType<IconProps> }[] = [
  { to: paths.today, label: 'Сегодня', Icon: SunIcon },
  { to: paths.calendar, label: 'Календарь', Icon: CalendarIcon },
  { to: paths.biorhythms, label: 'Биоритмы', Icon: ActivityIcon },
  { to: paths.settings, label: 'Настройки', Icon: SlidersIcon },
]

function UserCard() {
  const userName = useSessionStore(selectUserName)
  const initial = userName?.charAt(0).toUpperCase() ?? '?'

  return (
    <div className={styles.user}>
      <span className={styles.avatar} aria-hidden="true">
        {initial}
      </span>
      <span className={`text-label ${styles.userName}`}>{userName}</span>
      <LogoutButton />
    </div>
  )
}

export function AppLayout() {
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className="text-heading">Идеальный день</span>
          <ThemeToggle />
        </div>
        <nav aria-label="Основная навигация" className={styles.nav}>
          {NAVIGATION.map(({ to, label, Icon }) => (
            <SidebarLink key={to} to={to} className={styles.navLink}>
              <Icon />
              <span>{label}</span>
            </SidebarLink>
          ))}
        </nav>
        <div className={styles.footer}>
          <ServerStatus />
          <UserCard />
        </div>
      </aside>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  )
}
