import { useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { cx } from '@/shared/lib/cx'
import { BIORHYTHM_CYCLES, BIORHYTHM_PHASES, type BiorhythmCycle } from '@/shared/model/biorhythm'
import { Button } from '@/shared/ui/button/Button'
import { AlertTriangleIcon, CheckIcon } from '@/shared/ui/icon/icons'
import { Toggle } from '@/shared/ui/toggle/Toggle'
import {
  CYCLE_ORDER,
  PLOT,
  curvePath,
  formatDate,
  formatPercent,
  nearestPointIndex,
  pointX,
  pointY,
  type BiorhythmChartData,
} from './biorhythmChartModel'
import styles from './BiorhythmChart.module.css'

type BiorhythmChartProps = {
  data: BiorhythmChartData
  selectedAt: string | null
  onSelect: (at: string) => void
  referenceDate?: string
}

export function BiorhythmChart({ data, selectedAt, onSelect, referenceDate }: BiorhythmChartProps) {
  const [visible, setVisible] = useState<BiorhythmCycle[]>([...CYCLE_ORDER])
  const [showCritical, setShowCritical] = useState(true)
  const [showTooltip, setShowTooltip] = useState(true)
  const [width, setWidth] = useState(1128)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const id = useId()
  const points = data.points
  const hasPoints = points.length > 0
  const index = Math.max(
    0,
    points.findIndex((point) => point.at === selectedAt),
  )
  const selected = points[index]
  const reference = points.find((point) => point.date === referenceDate)
  const selectedX = selected ? pointX(selected.at, points, width) : 0
  const step = Math.max(
    1,
    Math.ceil((points.length - 1) / Math.max(2, Math.floor((width - 48) / 80))),
  )
  const ticks = points
    .map((point, index) => ({ point, index }))
    .filter(({ index }) => index % step === 0 || index === points.length - 1)
  const criticalDays = [
    ...new Map(
      points.filter((point) => point.critical.level > 0).map((point) => [point.date, point]),
    ).values(),
  ]

  useEffect(() => {
    const element = wrapperRef.current
    if (!element) return
    const measure = () => {
      const next = element.getBoundingClientRect().width
      if (next > 0) setWidth(Math.max(240, next))
    }
    measure()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure)
      return () => window.removeEventListener('resize', measure)
    }
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [hasPoints])

  const selectIndex = (next: number) => {
    if (!points.length) return
    onSelect(points[Math.max(0, Math.min(points.length - 1, next))].at)
    setShowTooltip(true)
  }
  const keyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    const next = {
      ArrowRight: index + 1,
      ArrowUp: index + 1,
      ArrowLeft: index - 1,
      ArrowDown: index - 1,
      Home: 0,
      End: points.length - 1,
    }[event.key]
    if (next !== undefined) {
      event.preventDefault()
      selectIndex(next)
    }
    if (event.key === 'Escape') setShowTooltip(false)
  }
  const pointer = (event: PointerEvent<SVGSVGElement>) => {
    if (event.type === 'pointermove' && event.pointerType === 'touch') return
    const bounds = event.currentTarget.getBoundingClientRect()
    if (!bounds.width) return
    selectIndex(
      nearestPointIndex(points, ((event.clientX - bounds.left) / bounds.width) * width, width),
    )
  }
  const selectedLabel = selected
    ? formatDate(selected.date, { weekday: 'short', day: 'numeric', month: 'long' })
    : ''
  const axisLabel = (at: string, date: string) =>
    data.step === 'hour'
      ? new Intl.DateTimeFormat('ru-RU', {
          timeZone: data.timezone,
          hour: '2-digit',
          minute: '2-digit',
        }).format(new Date(at))
      : formatDate(date, {
          day: 'numeric',
          ...(data.start.slice(0, 7) !== data.end.slice(0, 7) ? { month: 'short' } : {}),
        })

  return (
    <section className={styles.chart} aria-label="График биоритмов">
      <div className={styles.controls}>
        <div className={styles.legend} role="group" aria-label="Отображаемые циклы">
          {CYCLE_ORDER.map((cycle) => (
            <Button
              key={cycle}
              variant="secondary"
              className={styles.legendButton}
              data-cycle={cycle}
              aria-pressed={visible.includes(cycle)}
              onClick={() =>
                setVisible((current) =>
                  current.includes(cycle)
                    ? current.filter((value) => value !== cycle)
                    : [...current, cycle],
                )
              }
            >
              <span className={styles.check}>
                {visible.includes(cycle) ? <CheckIcon size={16} /> : null}
              </span>
              <span className={styles.lineSample} aria-hidden="true" />
              <span>
                {BIORHYTHM_CYCLES[cycle].label}
                <span className={styles.cyclePeriod}>
                  {' '}
                  · {BIORHYTHM_CYCLES[cycle].periodDays} {cycle === 'emotional' ? 'дней' : 'дня'}
                </span>
              </span>
            </Button>
          ))}
        </div>
        <label className={styles.criticalToggle}>
          <span>Показывать критические дни</span>
          <Toggle
            checked={showCritical}
            aria-label="Показывать критические дни"
            onCheckedChange={setShowCritical}
          />
        </label>
      </div>
      {!points.length ? (
        <div className={styles.empty} role="status">
          Нет данных за этот период.
        </div>
      ) : (
        <>
          <p className="visually-hidden" id={`${id}-instructions`}>
            Используйте стрелки для выбора точки, Home и End для начала и конца периода. Значения
            доступны в подсказке и таблице.
          </p>
          <div className={styles.plotWrap} ref={wrapperRef}>
            <svg
              className={styles.plot}
              viewBox={`0 0 ${width} ${PLOT.height}`}
              width={width}
              height={PLOT.height}
              role="slider"
              tabIndex={0}
              aria-label="Дата на графике биоритмов"
              aria-orientation="horizontal"
              aria-valuemin={0}
              aria-valuemax={points.length - 1}
              aria-valuenow={index}
              aria-valuetext={`${selectedLabel}${data.step === 'hour' ? `, ${axisLabel(selected.at, selected.date)}` : ''}. ${visible.map((cycle) => `${BIORHYTHM_CYCLES[cycle].label}: ${formatPercent(selected.cycles[cycle].percent)}`).join('. ')}`}
              aria-describedby={`${id}-instructions`}
              onKeyDown={keyDown}
              onPointerMove={pointer}
              onPointerDown={pointer}
              onPointerLeave={() => setShowTooltip(false)}
              onFocus={() => setShowTooltip(true)}
            >
              <defs>
                <clipPath id={`${id}-clip`}>
                  <rect
                    x={PLOT.left - 1}
                    y={PLOT.top - 10}
                    width={width - PLOT.left - PLOT.right + 2}
                    height={PLOT.bottom - PLOT.top + 20}
                  />
                </clipPath>
              </defs>
              <g aria-hidden="true">
                {showCritical &&
                  criticalDays.map((point) => {
                    const first = points.findIndex((item) => item.date === point.date)
                    const last = points.findLastIndex((item) => item.date === point.date)
                    const start = first
                      ? (pointX(points[first - 1].at, points, width) +
                          pointX(points[first].at, points, width)) /
                        2
                      : PLOT.left
                    const end =
                      last < points.length - 1
                        ? (pointX(points[last].at, points, width) +
                            pointX(points[last + 1].at, points, width)) /
                          2
                        : width - PLOT.right
                    return (
                      <rect
                        key={point.date}
                        data-critical-date={point.date}
                        className={styles.criticalBand}
                        x={start}
                        y={PLOT.top - 10}
                        width={Math.max(2, end - start)}
                        height={PLOT.bottom - PLOT.top + 20}
                        rx={4}
                      />
                    )
                  })}
                {[100, 0, -100].map((value) => (
                  <g key={value}>
                    <line
                      className={cx(styles.grid, value === 0 && styles.zeroGrid)}
                      x1={PLOT.left}
                      x2={width - PLOT.right}
                      y1={pointY(value)}
                      y2={pointY(value)}
                    />
                    <text className={styles.axisLabel} x={0} y={pointY(value) + 4}>
                      {value > 0 ? '+100' : value === 0 ? '0' : '−100'}
                    </text>
                  </g>
                ))}
                <g clipPath={`url(#${id}-clip)`}>
                  {visible.map((cycle) => (
                    <path
                      key={cycle}
                      data-cycle={cycle}
                      className={styles.curve}
                      d={curvePath(
                        points.map((point) => ({
                          x: pointX(point.at, points, width),
                          y: pointY(point.cycles[cycle].percent),
                        })),
                      )}
                    />
                  ))}
                  {showCritical &&
                    criticalDays.flatMap((point) =>
                      point.critical.crossings
                        .filter((crossing) => visible.includes(crossing.cycle))
                        .map((crossing) => (
                          <circle
                            key={`${crossing.cycle}-${crossing.at}`}
                            className={styles.crossing}
                            data-cycle={crossing.cycle}
                            cx={pointX(crossing.at, points, width)}
                            cy={pointY(0)}
                            r={3}
                          />
                        )),
                    )}
                  {reference && reference.at !== selected.at ? (
                    <line
                      className={styles.referenceLine}
                      x1={pointX(reference.at, points, width)}
                      x2={pointX(reference.at, points, width)}
                      y1={PLOT.top - 10}
                      y2={PLOT.bottom + 10}
                    />
                  ) : null}
                  <line
                    className={cx(
                      styles.selectionLine,
                      reference?.at === selected.at && styles.referenceLine,
                    )}
                    x1={selectedX}
                    x2={selectedX}
                    y1={PLOT.top - 10}
                    y2={PLOT.bottom + 10}
                  />
                  {visible.map((cycle) => (
                    <circle
                      key={cycle}
                      className={styles.selectedDot}
                      data-cycle={cycle}
                      cx={selectedX}
                      cy={pointY(selected.cycles[cycle].percent)}
                      r={5}
                    />
                  ))}
                </g>
                {reference && (
                  <g
                    transform={`translate(${Math.max(PLOT.left, Math.min(width - 140, pointX(reference.at, points, width) - 60))},0)`}
                  >
                    <rect className={styles.referenceBadge} width={128} height={24} rx={6} />
                    <text className={styles.referenceLabel} x={64} y={16} textAnchor="middle">
                      Сегодня, {formatDate(reference.date, { day: 'numeric', month: 'short' })}
                    </text>
                  </g>
                )}
                {ticks.map(({ point, index }) => (
                  <text
                    key={point.at}
                    className={cx(
                      styles.axisLabel,
                      showCritical && point.critical.level > 0 && styles.criticalLabel,
                    )}
                    x={pointX(point.at, points, width)}
                    y={PLOT.height - 5}
                    textAnchor={
                      index === points.length - 1 ? 'end' : index === 0 ? 'start' : 'middle'
                    }
                  >
                    {axisLabel(point.at, point.date)}
                  </text>
                ))}
              </g>
            </svg>
            {showTooltip && visible.length > 0 ? (
              <div
                className={styles.tooltip}
                role="status"
                style={{
                  left: Math.max(
                    8,
                    Math.min(width - 308, selectedX + (selectedX > width - 330 ? -316 : 16)),
                  ),
                }}
              >
                <p className="text-label-s">
                  {selectedLabel}
                  {data.step === 'hour' ? ` · ${axisLabel(selected.at, selected.date)}` : ''}
                </p>
                {CYCLE_ORDER.filter((cycle) => visible.includes(cycle)).map((cycle) => (
                  <div className={styles.tooltipRow} key={cycle} data-cycle={cycle}>
                    <span className={styles.dot} />
                    <span>{BIORHYTHM_CYCLES[cycle].label}</span>
                    <span>
                      {formatPercent(selected.cycles[cycle].percent)} ·{' '}
                      {BIORHYTHM_PHASES[selected.cycles[cycle].phase].toLowerCase()}
                    </span>
                  </div>
                ))}
                {selected.critical.level > 0 ? (
                  <p className={styles.criticalNote}>
                    <AlertTriangleIcon size={14} />
                    {selected.critical.level > 1
                      ? 'Пересечение нескольких циклов'
                      : 'Критический день'}
                  </p>
                ) : null}
              </div>
            ) : null}
            {!visible.length ? (
              <p className={styles.noCycles} role="status">
                Выберите хотя бы один цикл в легенде.
              </p>
            ) : null}
          </div>
          <p className={styles.caption}>
            Даты и время: {data.timezone}. Наведите на график или коснитесь его, чтобы посмотреть
            значения.
          </p>
          <div className={styles.summaries} aria-label={`Фазы циклов: ${selectedLabel}`}>
            {CYCLE_ORDER.map((cycle) => {
              const reading = selected.cycles[cycle]
              const nextCritical = points.find(
                (point) =>
                  point.date >= selected.date &&
                  point.critical.crossings.some((crossing) => crossing.cycle === cycle),
              )
              return (
                <section
                  key={cycle}
                  className={styles.summary}
                  data-cycle={cycle}
                  aria-label={BIORHYTHM_CYCLES[cycle].label}
                >
                  <p className={styles.summaryLabel}>
                    <span className={styles.lineSample} />
                    {BIORHYTHM_CYCLES[cycle].label} · {BIORHYTHM_CYCLES[cycle].periodDays}{' '}
                    {cycle === 'emotional' ? 'дней' : 'дня'}
                  </p>
                  <h2 className={styles.phase}>{BIORHYTHM_PHASES[reading.phase]}</h2>
                  <p className={styles.muted}>
                    {formatPercent(reading.percent)} ·{' '}
                    {reading.trend === 'up' ? 'значение растёт' : 'значение снижается'}
                  </p>
                  {nextCritical && (
                    <p className={styles.nextCritical}>
                      <AlertTriangleIcon size={13} />
                      Критический день —{' '}
                      {formatDate(nextCritical.date, {
                        weekday: 'short',
                        day: 'numeric',
                        month: 'short',
                      })}
                    </p>
                  )}
                </section>
              )
            })}
            <section className={styles.readingGuide}>
              <h2 className="text-label">Как читать график</h2>
              <p>Выше нуля — подъём, ниже — спад.</p>
              <p>Жёлтая колонка — критический день: цикл пересекает ноль.</p>
              <p>Цвета линий соответствуют трём циклам. Значения показаны в процентах.</p>
            </section>
          </div>
          <details className={styles.tableDetails}>
            <summary>Значения в таблице</summary>
            <div className={styles.tableScroll}>
              <table>
                <caption>Биоритмы за выбранный период · {data.timezone}</caption>
                <thead>
                  <tr>
                    <th scope="col">Дата{data.step === 'hour' ? ' и время' : ''}</th>
                    {CYCLE_ORDER.map((cycle) => (
                      <th scope="col" key={cycle}>
                        {BIORHYTHM_CYCLES[cycle].label}
                      </th>
                    ))}
                    <th scope="col">Критические циклы</th>
                  </tr>
                </thead>
                <tbody>
                  {points.map((point) => (
                    <tr key={point.at}>
                      <th scope="row">
                        {formatDate(point.date, { day: 'numeric', month: 'short' })}
                        {data.step === 'hour'
                          ? ` ${axisLabel(point.at, point.date)} (${new Intl.DateTimeFormat('en', { timeZone: data.timezone, timeZoneName: 'shortOffset' }).formatToParts(new Date(point.at)).find((part) => part.type === 'timeZoneName')?.value})`
                          : ''}
                      </th>
                      {CYCLE_ORDER.map((cycle) => (
                        <td key={cycle}>{formatPercent(point.cycles[cycle].percent)}</td>
                      ))}
                      <td>
                        {point.critical.crossings
                          .map((crossing) => BIORHYTHM_CYCLES[crossing.cycle].label)
                          .join(', ') || 'Нет'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </section>
  )
}
