import { useId } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { getBiorhythmCriticalDays } from '@/shared/api/biorhythm'
import { Button } from '@/shared/ui/button/Button'
import { AlertTriangleIcon } from '@/shared/ui/icon/icons'
import { useSessionStore } from '@/stores/session'
import { addDays } from '@/pages/biorhythms/biorhythmChartModel'
import { taskSessionRequest } from './taskSessionRequest'
import { criticalDayCopy } from './todayHeaderModel'
import styles from './TodayPage.module.css'

export function TodayCriticalDays({ date }: { date: string }) {
  const generation = useSessionStore((state) => state.generation)
  const timezone = useSessionStore((state) => state.timezone)
  const owner = useSessionStore((state) => state.ownerId)
  const birthDate = useSessionStore((state) => state.user?.birthDate)
  const birthTime = useSessionStore((state) => state.user?.birthTime)
  const status = useSessionStore((state) => state.status)
  const navigate = useNavigate()
  const id = useId()
  const end = addDays(date, 6)
  const enabled = status === 'authenticated' && Boolean(birthDate)
  const query = useQuery({
    queryKey: [
      'biorhythms',
      'critical-days',
      generation,
      owner,
      timezone,
      birthDate,
      birthTime,
      date,
      end,
    ],
    enabled,
    queryFn: ({ signal }) =>
      taskSessionRequest(
        generation,
        async (requestSignal) => {
          const result = await getBiorhythmCriticalDays({ from: date, to: end }, requestSignal)
          if (result.timezone !== timezone) throw new Error('Часовой пояс профиля изменился.')
          return result
        },
        signal,
      ),
    retry: false,
    gcTime: 0,
  })
  if (!enabled) return null
  if (query.isPending || query.isFetching)
    return (
      <p className={styles.criticalState} role="status">
        Проверяем ближайшие критические дни…
      </p>
    )
  if (query.isError)
    return (
      <div className={styles.criticalState} role="status">
        <p>Не удалось проверить ближайшие критические дни.</p>
        <Button variant="ghost" size="s" onClick={() => void query.refetch()}>
          Повторить проверку
        </Button>
      </div>
    )
  if (!query.data?.days.length) return null
  const days = query.data.days.map((day) => day.date)
  const copy = criticalDayCopy(days, date)
  return (
    <section className={styles.criticalBanner} aria-labelledby={id}>
      <AlertTriangleIcon size={20} />
      <div>
        <h2 id={id} className={styles.criticalTitle}>
          {copy.title}
        </h2>
        <p>{copy.description}</p>
      </div>
      <Button
        variant="secondary"
        size="s"
        onClick={() => navigate(`${paths.biorhythms}?period=week&date=${days[0]}`)}
      >
        Открыть неделю
      </Button>
    </section>
  )
}
