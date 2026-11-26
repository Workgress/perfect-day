import { useId, useSyncExternalStore } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { paths } from '@/app/router/paths'
import { scheduleKeys, taskKeys } from '@/shared/api/planningKeys'
import type { SavedSchedule } from '@/shared/model/schedule'
import type { Task } from '@/shared/model/task'
import { apiError } from '@/shared/api/errors'
import { BIORHYTHM_CYCLES } from '@/shared/model/biorhythm'
import { biorhythmStateLabel } from '@/shared/lib/biorhythmStateLabel'
import { Button } from '@/shared/ui/button/Button'
import { ChevronRightIcon } from '@/shared/ui/icon/icons'
import { useSessionStore } from '@/stores/session'
import { CYCLE_ORDER, formatDate, formatPercent } from '@/pages/biorhythms/biorhythmChartModel'
import { useTodayBiorhythms } from './useTodayBiorhythms'
import { cycleTaskHint, daysSinceBirthLabel } from './todayEnergyModel'
import styles from './TodayDashboard.module.css'
import { EnergyLoading } from './TodayLoading'

export function TodayEnergyProfile({ date }: { date: string }) {
  const id = useId()
  const generation = useSessionStore((state) => state.generation)
  const timezone = useSessionStore((state) => state.timezone)
  const user = useSessionStore((state) => state.user)
  const status = useSessionStore((state) => state.status)
  const enabled = status === 'authenticated' && Boolean(user?.birthDate)
  const cache = useQueryClient().getQueryCache()
  const saved = useSyncExternalStore(
    (listener) => cache.subscribe(listener),
    () =>
      cache.find<SavedSchedule>({ queryKey: scheduleKeys.day(generation, date), exact: true })
        ?.state,
  )
  const tasks = useSyncExternalStore(
    (listener) => cache.subscribe(listener),
    () => cache.find<Task[]>({ queryKey: taskKeys.day(generation, date), exact: true })?.state,
  )
  const schedule =
    saved?.fetchStatus === 'idle' &&
    saved.status !== 'error' &&
    tasks?.fetchStatus === 'idle' &&
    tasks.status !== 'error' &&
    saved.data?.timezone === timezone
      ? saved.data
      : undefined
  const query = useTodayBiorhythms(date)
  const data = !query.isError && !query.isFetching ? query.data : undefined
  const series = data?.series
  const today = series?.points.find((point) => point.date === date)
  const chronotype = user?.chronotype
    ? { lark: 'жаворонок', owl: 'сова', dove: 'голубь' }[user.chronotype]
    : null
  return (
    <section className={styles.energy} aria-labelledby={id}>
      <header className={styles.energyHeader}>
        <div>
          <h2 id={id}>
            <span className={styles.desktopTitle}>Энергетический профиль на сегодня</span>
            <span className={styles.mobileTitle}>Энергия на сегодня</span>
          </h2>
          <p className={styles.context}>
            {enabled && (query.isPending || query.isFetching)
              ? 'Считаем циклы по дате рождения…'
              : user?.birthDate
                ? `Рассчитан по дате рождения ${formatDate(user.birthDate, { day: '2-digit', month: '2-digit', year: 'numeric' })} · ${daysSinceBirthLabel(user.birthDate, date)}${chronotype ? ` · хронотип «${chronotype}»` : ''}`
                : 'Укажите дату рождения в профиле для расчёта биоритмов.'}
          </p>
        </div>
        <Link className={styles.forecastLink} to={`${paths.biorhythms}?period=week&date=${date}`}>
          Графики и прогноз <ChevronRightIcon size={16} />
        </Link>
      </header>
      {!enabled ? null : query.isPending || query.isFetching ? (
        <EnergyLoading />
      ) : query.isError ? (
        <div className={styles.dataState} role="status">
          <p>Не удалось загрузить биоритмы. {apiError(query.error)}</p>
          <Button variant="ghost" size="s" onClick={() => void query.refetch()}>
            Повторить загрузку биоритмов
          </Button>
        </div>
      ) : series && today ? (
        <div className={styles.cycles}>
          {CYCLE_ORDER.map((cycle) => {
            const reading = today.cycles[cycle]
            const x = (index: number) => 4 + (index / (series.points.length - 1)) * 346
            const y = (percent: number) => 22 - (percent / 100) * 18
            const todayX = x(series.points.indexOf(today))
            const nextCrossing = data?.critical.days.find(
              (point) =>
                point.date >= date && point.crossings.some((crossing) => crossing.cycle === cycle),
            )
            const taskHint =
              schedule && tasks?.data ? cycleTaskHint(cycle, tasks.data, schedule) : ''
            return (
              <article
                key={cycle}
                className={styles.cycle}
                style={{ color: `var(--bio-${cycle})` }}
                aria-label={`${BIORHYTHM_CYCLES[cycle].label} цикл`}
              >
                <svg
                  className={styles.curve}
                  viewBox="0 0 354 44"
                  preserveAspectRatio="none"
                  role="img"
                  aria-label={`${BIORHYTHM_CYCLES[cycle].label} цикл: ${formatPercent(reading.percent)}, ${biorhythmStateLabel(reading)}`}
                >
                  <path d="M0 22H354" className={styles.zero} />
                  <polyline
                    points={series.points
                      .map((point, index) => `${x(index)},${y(point.cycles[cycle].percent)}`)
                      .join(' ')}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    vectorEffect="non-scaling-stroke"
                  />
                  <path d={`M${todayX} 0V44`} className={styles.todayMarker} />
                  <circle cx={todayX} cy={y(reading.percent)} r="4" fill="currentColor" />
                </svg>
                <h3>
                  <span
                    className={styles.cycleSwatch}
                    style={{ background: `var(--bio-${cycle})` }}
                    aria-hidden="true"
                  />
                  <span>
                    {BIORHYTHM_CYCLES[cycle].label} · {BIORHYTHM_CYCLES[cycle].periodDays}{' '}
                    {cycle === 'emotional' ? 'дней' : 'дня'}
                  </span>
                </h3>
                <div className={styles.reading}>
                  <strong>{formatPercent(reading.percent)}</strong>
                  <span>{biorhythmStateLabel(reading)}</span>
                </div>
                <p className={styles.cycleHint}>
                  {taskHint ? `${taskHint} ` : ''}
                  {nextCrossing
                    ? `Критический день — ${formatDate(nextCrossing.date, { weekday: 'short', day: 'numeric', month: 'long' })}.`
                    : 'Критических дней в ближайшие 33 дня нет.'}
                </p>
              </article>
            )
          })}
        </div>
      ) : (
        <p className={styles.dataState}>На сегодня нет данных биоритмов.</p>
      )}
    </section>
  )
}
