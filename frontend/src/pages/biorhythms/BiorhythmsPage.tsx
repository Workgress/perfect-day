import { useEffect, useRef, useState } from 'react'
import { apiError } from '@/shared/api/errors'
import { useSessionStore } from '@/stores/session'
import { BIORHYTHM_CYCLES } from '@/shared/model/biorhythm'
import { Button } from '@/shared/ui/button/Button'
import {
  AlertTriangleIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  InfoIcon,
} from '@/shared/ui/icon/icons'
import { PageHeader } from '@/shared/ui/page-header/PageHeader'
import * as Segment from '@/shared/ui/segment/Segment'
import { BiorhythmChart } from './BiorhythmChart'
import {
  CYCLE_ORDER,
  chartRange,
  formatDate,
  formatPercent,
  periodLabel,
  shiftPeriod,
  type ChartPeriod,
} from './biorhythmChartModel'
import styles from './BiorhythmsPage.module.css'
import { useBiorhythmData, useBiorhythmToday } from './useBiorhythmData'

const PERIODS = [
  { value: 'week', label: 'Неделя' },
  { value: 'month', label: 'Месяц' },
  { value: 'quarter', label: '3 месяца' },
] as const
export function BiorhythmsPage() {
  const generation = useSessionStore((state) => state.generation)
  const timezone = useSessionStore((state) => state.timezone)
  const owner = useSessionStore((state) => state.ownerId)
  const birthDate = useSessionStore((state) => state.user?.birthDate)
  const birthTime = useSessionStore((state) => state.user?.birthTime)
  return (
    <BiorhythmsContent
      key={`${generation}:${owner}:${timezone}:${birthDate}:${birthTime}`}
      timezone={timezone}
      birthDate={birthDate}
    />
  )
}

function BiorhythmsContent({
  timezone,
  birthDate,
}: {
  timezone: string
  birthDate?: string | null
}) {
  const today = useBiorhythmToday(timezone)
  const daysSinceBirth = birthDate
    ? Math.round((Date.parse(today) - Date.parse(birthDate)) / 86_400_000)
    : null
  const [period, setPeriod] = useState<ChartPeriod>('month')
  const [anchor, setAnchor] = useState(today)
  const [selectedAt, setSelectedAt] = useState<string | null>(null)
  const [showMethod, setShowMethod] = useState(false)
  const chartRef = useRef<HTMLDivElement>(null)
  const focusAfterLoad = useRef(false)
  const range = chartRange(anchor, period)
  const query = useBiorhythmData(range.start, range.end, today)
  const data = !query.isError && !query.isFetching ? query.data?.series : undefined
  const selected =
    data?.points.find((point) => point.at === selectedAt) ??
    data?.points.find((point) => point.date === today) ??
    data?.points[0]
  const forecast = data ? (query.data?.forecast.points ?? []) : []
  const criticalDays = data?.points.filter((point) => point.critical.level >= 2) ?? []
  const doubleCritical = criticalDays.find((point) => point.date >= today) ?? criticalDays[0]
  const criticalTitle =
    doubleCritical?.critical.level === 3 ? 'Тройной критический день' : 'Двойной критический день'

  useEffect(() => {
    if (!data || !focusAfterLoad.current) return
    focusAfterLoad.current = false
    chartRef.current
      ?.querySelector<SVGSVGElement>('[role="slider"]')
      ?.focus({ preventScroll: true })
    chartRef.current?.scrollIntoView?.({ block: 'nearest' })
  }, [data])

  const selectDay = (at: string) => {
    setSelectedAt(at)
    chartRef.current
      ?.querySelector<SVGSVGElement>('[role="slider"]')
      ?.focus({ preventScroll: true })
    chartRef.current?.scrollIntoView?.({ block: 'nearest' })
  }

  return (
    <div className={styles.page}>
      <title>Биоритмы · Идеальный день</title>
      <div className={styles.heading}>
        <p className={styles.context}>
          Классическая модель
          {birthDate && daysSinceBirth !== null ? (
            <>
              {' · дата рождения '}
              {formatDate(birthDate, { day: '2-digit', month: '2-digit', year: 'numeric' })}
              {' · день '}
              {new Intl.NumberFormat('ru-RU').format(daysSinceBirth)}
            </>
          ) : null}
        </p>
        <PageHeader title="Биоритмы">
          <div className={styles.periodNavigation} role="group" aria-label="Навигация по периоду">
            <Button
              variant="secondary"
              className={styles.arrow}
              aria-label="Предыдущий период"
              onClick={() => {
                focusAfterLoad.current = false
                setAnchor(shiftPeriod(anchor, period, -1))
                setSelectedAt(null)
              }}
            >
              <ChevronLeftIcon size={18} />
            </Button>
            <p className={styles.rangeLabel} aria-live="polite">
              {periodLabel(range.start, range.end, period)}
            </p>
            <Button
              variant="secondary"
              className={styles.arrow}
              aria-label="Следующий период"
              onClick={() => {
                focusAfterLoad.current = false
                setAnchor(shiftPeriod(anchor, period, 1))
                setSelectedAt(null)
              }}
            >
              <ChevronRightIcon size={18} />
            </Button>
          </div>
          <Segment.Root
            className={styles.periods}
            aria-label="Период графика"
            value={period}
            onValueChange={(value) => {
              focusAfterLoad.current = false
              setAnchor(selected?.date ?? anchor)
              setPeriod(value as ChartPeriod)
            }}
          >
            {PERIODS.map((option) => (
              <Segment.Item key={option.value} value={option.value}>
                {option.label}
              </Segment.Item>
            ))}
          </Segment.Root>
        </PageHeader>
      </div>
      <section className={styles.explanation} aria-label="Как циклы влияют на план">
        <InfoIcon size={18} />
        <div>
          <h2 className="text-label">Как циклы влияют на план</h2>
          <p>
            Фазы трёх циклов решают, какие задачи ставить в какие дни, а часы внутри дня подбираются
            по хронотипу. Если самочувствие расходится с прогнозом, план можно поправить вручную.
          </p>
          <div id="biorhythm-method" className={styles.method} hidden={!showMethod}>
            <p>
              Классическая модель использует физический цикл длиной 23 дня, эмоциональный — 28 дней
              и интеллектуальный — 33 дня. Фаза цикла и направление изменения значения отображаются
              отдельно.
            </p>
            <p>
              Это теоретическая модель, а не оценка вашего фактического самочувствия. Значения
              циклов и критические дни рассчитаны сервером по данным вашего профиля.
            </p>
          </div>
        </div>
        <button
          type="button"
          className={styles.methodButton}
          aria-expanded={showMethod}
          aria-controls="biorhythm-method"
          onClick={() => setShowMethod((current) => !current)}
        >
          {showMethod ? 'Свернуть' : 'О методике'}
          {showMethod ? <ChevronDownIcon size={14} /> : <ChevronRightIcon size={14} />}
        </button>
      </section>
      {query.isFetching ? (
        <div className={styles.requestState} role="status" aria-live="polite">
          Загружаем биоритмы…
        </div>
      ) : query.isError ? (
        <div className={styles.requestState} role="alert">
          <h2 className="text-label">Не удалось загрузить биоритмы</h2>
          <p>{apiError(query.error)}</p>
          <Button variant="secondary" onClick={() => void query.refetch()}>
            Повторить запрос
          </Button>
        </div>
      ) : !data ? (
        <div className={styles.requestState} role="status">
          Для расчёта заполните дату рождения в профиле.
        </div>
      ) : null}
      <div ref={chartRef}>
        {data ? (
          <BiorhythmChart
            data={data}
            selectedAt={selected?.at ?? null}
            onSelect={setSelectedAt}
            referenceDate={today}
          />
        ) : null}
      </div>
      {data ? (
        <section className={styles.forecast} aria-label="Прогноз на 7 дней">
          <header className={styles.forecastHeader}>
            <h2 className="text-heading">Прогноз на 7 дней</h2>
            <p>Значения циклов и критические дни</p>
          </header>
          <div className={styles.forecastGrid}>
            {forecast.map((point) => {
              return (
                <button
                  type="button"
                  key={point.date}
                  className={styles.forecastCard}
                  data-critical={point.critical.level > 0 || undefined}
                  aria-pressed={selected?.date === point.date}
                  aria-label={`Посмотреть ${formatDate(point.date, { day: 'numeric', month: 'long' })}`}
                  onClick={() => {
                    if (point.date < range.start || point.date > range.end) {
                      focusAfterLoad.current = true
                      setAnchor(point.date)
                    }
                    selectDay(point.at)
                  }}
                >
                  <span className={styles.forecastDate}>
                    {formatDate(point.date, { weekday: 'short', day: 'numeric' })}
                    {point.date === today ? <span> · сегодня</span> : null}
                  </span>
                  <span className={styles.forecastValues}>
                    {CYCLE_ORDER.map((cycle) => (
                      <span key={cycle} className={styles.forecastValue} data-cycle={cycle}>
                        <span aria-hidden="true" />
                        <span className="visually-hidden">{BIORHYTHM_CYCLES[cycle].label}: </span>
                        {formatPercent(point.cycles[cycle].percent)}
                      </span>
                    ))}
                  </span>
                  {point.critical.level > 0 ? (
                    <span className={styles.warning}>
                      <AlertTriangleIcon size={12} />
                      Критический
                    </span>
                  ) : null}
                </button>
              )
            })}
          </div>
        </section>
      ) : null}
      {doubleCritical ? (
        <section className={styles.criticalBanner} aria-label={criticalTitle}>
          <AlertTriangleIcon size={20} />
          <div>
            <h2 className="text-label">
              {criticalTitle} —{' '}
              {formatDate(doubleCritical.date, { weekday: 'short', day: 'numeric', month: 'long' })}
            </h2>
            <p>
              {doubleCritical.critical.crossings
                .map((crossing) => BIORHYTHM_CYCLES[crossing.cycle].label)
                .join(', ')}
              : циклы пересекают ноль в один локальный день.
            </p>
          </div>
          <Button variant="secondary" size="s" onClick={() => selectDay(doubleCritical.at)}>
            Посмотреть день
          </Button>
        </section>
      ) : data ? (
        <section className={styles.explanation} aria-label="Критические дни выбранного периода">
          <InfoIcon size={20} />
          <div>
            <h2 className="text-label">Двойных и тройных критических дней нет</h2>
            <p>
              В выбранном периоде сервер не определил пересечений нескольких циклов в один день.
            </p>
          </div>
        </section>
      ) : null}
    </div>
  )
}
