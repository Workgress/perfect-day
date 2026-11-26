import { useId } from 'react'
import { BIORHYTHM_CYCLES } from '@/shared/model/biorhythm'
import type { DailySchedule } from '@/shared/model/schedule'
import { ActivityIcon, ClockIcon, ZapIcon } from '@/shared/ui/icon/icons'
import { useSessionStore } from '@/stores/session'
import { formatPercent } from '@/pages/biorhythms/biorhythmChartModel'
import { timelineClock } from './timelineModel'
import { todayWindows } from './todayWindowsModel'
import { useTodayBiorhythms } from './useTodayBiorhythms'
import styles from './TodayDashboard.module.css'

export function TodayEmptyWindows({ day }: { day: DailySchedule }) {
  const id = useId()
  const chronotype = useSessionStore((state) => state.user?.chronotype)
  const query = useTodayBiorhythms(day.date)
  const today =
    !query.isError && !query.isFetching
      ? query.data?.series.points.find((point) => point.date === day.date)
      : undefined
  const windows = todayWindows(day, chronotype)
  const suggestions = [
    {
      window: windows.find((window) => window.type === 'intellectual'),
      cycle: 'intellectual' as const,
      label: 'сложная учёба',
      Icon: ZapIcon,
    },
    {
      window: windows.find((window) => window.type === 'physical'),
      cycle: 'physical' as const,
      label: 'спорт',
      Icon: ActivityIcon,
    },
    {
      window: windows.findLast((window) => window.type === 'routine'),
      cycle: 'emotional' as const,
      label: 'рутина',
      Icon: ClockIcon,
    },
  ]
  return (
    <aside className={styles.emptyWindows} aria-labelledby={id}>
      <h2 id={id}>Окна сегодня</h2>
      <p className={styles.windowContext}>Ориентиры по вашему хронотипу и рабочему времени.</p>
      {windows.length ? (
        <ul>
          {suggestions.map(({ window, cycle, label, Icon }) =>
            window ? (
              <li key={cycle}>
                <Icon size={20} />
                <div>
                  <p>
                    {timelineClock(window.start, day.timezone)}–
                    {timelineClock(window.end, day.timezone)} · {label}
                  </p>
                  <p className={styles.context}>
                    {today
                      ? `${BIORHYTHM_CYCLES[cycle].label} цикл ${formatPercent(today.cycles[cycle].percent)}.`
                      : 'Время выбрано по хронотипу.'}
                  </p>
                </div>
              </li>
            ) : null,
          )}
        </ul>
      ) : (
        <p className={styles.context}>
          Добавьте задачу — подберём время с учётом вашего режима дня.
        </p>
      )}
    </aside>
  )
}
