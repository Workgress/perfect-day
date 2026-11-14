import { useMemo, useRef, useState } from 'react'
import { createBiorhythmDemoPoints, BIORHYTHM_FIXTURES } from '@/shared/fixtures/biorhythms'
import { PLANNING_FIXTURE_CONTEXT } from '@/shared/fixtures/planning'
import { BIORHYTHM_CYCLES, BIORHYTHM_PHASES } from '@/shared/model/biorhythm'
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
  addDays,
  chartRange,
  formatDate,
  formatPercent,
  periodLabel,
  shiftPeriod,
  type ChartPeriod,
} from './biorhythmChartModel'
import styles from './BiorhythmsPage.module.css'

const PERIODS = [
  { value: 'week', label: 'Неделя' },
  { value: 'month', label: 'Месяц' },
  { value: 'quarter', label: '3 месяца' },
] as const
const REFERENCE_DATE = PLANNING_FIXTURE_CONTEXT.date
const SHORT_CYCLE_LABELS = {
  physical: 'Физический',
  emotional: 'Эмоции',
  intellectual: 'Интеллект',
}

export function BiorhythmsPage() {
  const [period, setPeriod] = useState<ChartPeriod>('month')
  const [anchor, setAnchor] = useState<string>(REFERENCE_DATE)
  const [selectedAt, setSelectedAt] = useState<string | null>(null)
  const [showMethod, setShowMethod] = useState(false)
  const chartRef = useRef<HTMLDivElement>(null)
  const range = chartRange(anchor, period)
  const data = useMemo(
    () => ({
      start: range.start,
      end: range.end,
      timezone: BIORHYTHM_FIXTURES.month.timezone,
      step: 'day' as const,
      points: createBiorhythmDemoPoints(range.start, range.end),
    }),
    [range.start, range.end],
  )
  const selected =
    data.points.find((point) => point.at === selectedAt) ??
    data.points.find((point) => point.date === REFERENCE_DATE) ??
    data.points[0]
  const forecast = useMemo(() => createBiorhythmDemoPoints(anchor, addDays(anchor, 6)), [anchor])
  const doubleCritical = data.points.find(
    (point) => point.date >= anchor && point.critical.level >= 2,
  )

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
        <p className={styles.demo}>Демонстрационные данные · не относятся к вашему профилю</p>
        <PageHeader title="Биоритмы">
          <div className={styles.periodNavigation} role="group" aria-label="Навигация по периоду">
            <Button
              variant="secondary"
              className={styles.arrow}
              aria-label="Предыдущий период"
              onClick={() => {
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
              Это теоретическая модель, а не оценка вашего фактического самочувствия. В этой
              демонстрации показаны синтетические значения для проверки интерфейса.
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
      <div ref={chartRef}>
        <BiorhythmChart
          data={data}
          selectedAt={selected?.at ?? null}
          onSelect={setSelectedAt}
          referenceDate={REFERENCE_DATE}
        />
      </div>
      <section className={styles.forecast} aria-label="Прогноз на 7 дней">
        <header className={styles.forecastHeader}>
          <h2 className="text-heading">Прогноз на 7 дней</h2>
          <p>Фазы и значения трёх циклов</p>
        </header>
        <div className={styles.forecastGrid}>
          {forecast.map((point) => {
            const highest = CYCLE_ORDER.reduce(
              (best, cycle) =>
                point.cycles[cycle].percent > point.cycles[best].percent ? cycle : best,
              CYCLE_ORDER[0] as (typeof CYCLE_ORDER)[number],
            )
            return (
              <button
                type="button"
                key={point.date}
                className={styles.forecastCard}
                data-critical={point.critical.level > 0 || undefined}
                aria-pressed={selected?.date === point.date}
                aria-label={`Посмотреть ${formatDate(point.date, { day: 'numeric', month: 'long' })}`}
                onClick={() => {
                  if (point.date < range.start || point.date > range.end) setAnchor(point.date)
                  selectDay(point.at)
                }}
              >
                <span className={styles.forecastDate}>
                  {formatDate(point.date, { weekday: 'short', day: 'numeric' })}
                  {point.date === REFERENCE_DATE ? <span> · демо</span> : null}
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
                <span className={styles.forecastPhase}>
                  {SHORT_CYCLE_LABELS[highest]}:{' '}
                  {BIORHYTHM_PHASES[point.cycles[highest].phase].toLowerCase()}
                </span>
              </button>
            )
          })}
        </div>
      </section>
      {doubleCritical ? (
        <section className={styles.criticalBanner} aria-label="Двойной критический день">
          <AlertTriangleIcon size={20} />
          <div>
            <h2 className="text-label">
              Ближайшее пересечение нескольких циклов —{' '}
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
      ) : null}
    </div>
  )
}
