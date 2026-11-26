import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { getSchedule } from '@/shared/api/schedule'
import { getBiorhythmSeries } from '@/shared/api/biorhythm'
import { apiProblem } from '@/shared/api/errors'
import {
  isCalendarDate,
  localDate,
  localDateTime,
  resolveLocalDateTime,
} from '@/shared/lib/dateTime'
import type { TaskType } from '@/shared/model/task'
import { TASK_TYPES } from '@/shared/model/task'
import { useSessionStore } from '@/stores/session'
import { Button } from '@/shared/ui/button/Button'
import { TextField } from '@/shared/ui/form-field/FormField'
import { ClockIcon, ChevronRightIcon, XIcon } from '@/shared/ui/icon/icons'
import { taskSessionRequest } from './taskSessionRequest'
import { useTaskDialog } from './useTaskDialog'
import type { TaskFormContext } from './taskFormModel'
import { nextTaskDays, taskTimeLabel, taskTimeOptions } from './taskTimeOptions'
import styles from './TaskTimeChooser.module.css'

type Props = {
  context: TaskFormContext
  date: string
  duration: number | ''
  type: TaskType | ''
  deadline: string
  value: string
  mobile: boolean
  onSelect: (value: string) => void
  onClose: () => void
}

export function TaskTimeChooser(props: Props) {
  return props.mobile ? <TimeSheet {...props} /> : <TimeChoices {...props} />
}

function TimeSheet(props: Props) {
  const { dialogRef, onKeyDown } = useTaskDialog(
    props.onClose,
    '[data-task-time-trigger]',
    'input:checked, input, button',
  )
  return createPortal(
    <dialog
      ref={dialogRef}
      className={styles.sheet}
      aria-label="Когда поставить"
      onKeyDown={(event) => {
        event.stopPropagation()
        if (event.key === 'Escape') {
          event.preventDefault()
          props.onClose()
          return
        }
        onKeyDown(event)
      }}
      onCancel={(event) => {
        event.preventDefault()
        event.stopPropagation()
        props.onClose()
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          const box = event.currentTarget.getBoundingClientRect()
          if (event.clientY < box.top || event.clientY > box.bottom) props.onClose()
        }
      }}
    >
      <div className={styles.grabber} aria-hidden="true" />
      <TimeChoices {...props} />
    </dialog>,
    document.body,
  )
}

function TimeChoices({
  context,
  date,
  duration,
  type,
  deadline,
  value,
  mobile,
  onSelect,
  onClose,
}: Props) {
  const id = useId()
  const sectionRef = useRef<HTMLElement>(null)
  const manualRef = useRef<HTMLDivElement>(null)
  const generation = useSessionStore((state) => state.generation)
  const [now] = useState(() => context.now ?? new Date())
  const today = localDate(now, context.timezone)
  const first = isCalendarDate(date) && date >= today ? date : today
  const dates = nextTaskDays(first)
  const [manual, setManual] = useState(Boolean(value))
  const [selected, setSelected] = useState(value)
  const [manualValue, setManualValue] = useState(value || `${first}T`)
  const query = useQuery({
    queryKey: ['task-time-options', generation, first, context.timezone],
    retry: false,
    staleTime: 0,
    queryFn: ({ signal }) =>
      taskSessionRequest(
        generation,
        async (requestSignal) => {
          const [plans, bio] = await Promise.all([
            Promise.allSettled(
              dates.map(async (day) => {
                try {
                  return { date: day, schedule: await getSchedule(day, requestSignal) }
                } catch (error) {
                  if (apiProblem(error)?.code === 'SCHEDULE_NOT_FOUND')
                    return { date: day, schedule: null }
                  throw error
                }
              }),
            ),
            getBiorhythmSeries(
              { from: dates[0], to: dates.at(-1)!, step: 'hour' },
              requestSignal,
            ).catch(() => undefined),
          ])
          requestSignal.throwIfAborted()
          return {
            days: plans.flatMap((result) =>
              result.status === 'fulfilled' &&
              (!result.value.schedule || result.value.schedule.timezone === context.timezone)
                ? [result.value]
                : [],
            ),
            rhythms: bio,
            failed: plans.some(
              (result) =>
                result.status === 'rejected' ||
                (result.value.schedule && result.value.schedule.timezone !== context.timezone),
            ),
          }
        },
        signal,
      ),
  })
  const options = taskTimeOptions({
    ...context,
    days: query.data?.days ?? [],
    rhythms: query.data?.rhythms,
    duration,
    type,
    now,
    deadline,
  })
  useEffect(() => {
    if (!mobile && query.data) sectionRef.current?.scrollIntoView?.({ block: 'start' })
  }, [mobile, query.data])
  const selectedStart =
    selected || (options[0] ? localDateTime(new Date(options[0].start), context.timezone) : '')
  const chosen = manual ? manualValue : selectedStart
  const resolved = resolveLocalDateTime(chosen, context.timezone)
  const valid = resolved.status === 'valid'
  const canSelect =
    valid &&
    (manual ||
      options.some(
        (option) => localDateTime(new Date(option.start), context.timezone) === selectedStart,
      ))
  const [manualDate = '', manualTime = ''] = manualValue.split('T')
  const apply = () => {
    if (canSelect) {
      onSelect(chosen)
      onClose()
    }
  }

  return (
    <section
      ref={sectionRef}
      className={styles.choices}
      aria-labelledby={`${id}-heading`}
      onKeyDown={(event) => {
        if (!mobile && event.key === 'Escape') {
          event.preventDefault()
          event.stopPropagation()
          onClose()
          return
        }
        if (event.key === 'Enter' && event.target instanceof HTMLInputElement) {
          event.preventDefault()
          apply()
        }
      }}
    >
      <header className={styles.header}>
        <div>
          <h3 id={`${id}-heading`}>Когда поставить</h3>
          <p className={styles.caption}>
            {type ? TASK_TYPES[type] : 'Выберите тип'} ·{' '}
            {duration ? `${duration} мин` : 'Укажите длительность'}
          </p>
        </div>
        <Button variant="ghost" size="s" aria-label="Закрыть выбор времени" onClick={onClose}>
          <XIcon />
        </Button>
      </header>
      {query.isPending ? (
        <p role="status" className={styles.caption}>
          Ищем свободные окна…
        </p>
      ) : null}
      {!query.isPending && (query.isError || query.data?.failed) ? (
        <div className={styles.notice}>
          <p>Не удалось проверить часть расписания. Показываем только проверенные дни.</p>
          <Button variant="ghost" size="s" onClick={() => void query.refetch()}>
            Повторить
          </Button>
        </div>
      ) : null}
      {!query.isPending && !options.length ? (
        <p className={styles.caption}>
          {!type || !duration
            ? 'Выберите тип и длительность, чтобы увидеть подходящие интервалы.'
            : query.data?.days.length
              ? 'На ближайшие 7 дней свободных окон нужной длительности нет. Можно указать другое время вручную.'
              : 'Свободные окна недоступны. Укажите время вручную или повторите загрузку.'}
        </p>
      ) : null}
      <fieldset className={styles.options} aria-label="Свободное время">
        {options.map((option, index) => {
          const local = localDateTime(new Date(option.start), context.timezone)
          return (
            <label className={styles.option} key={option.start}>
              <input
                type="radio"
                name={`${id}-time`}
                checked={!manual && selectedStart === local}
                onChange={() => {
                  setManual(false)
                  setSelected(local)
                }}
              />
              <span>
                <span className={styles.optionTitle}>
                  {taskTimeLabel(option.start, option.end, context.timezone, now)}
                </span>
                <span className={styles.caption}>
                  {index === 0 && query.data?.rhythms ? 'Лучшее из свободных окон · ' : ''}
                  {option.explanation}
                </span>
              </span>
            </label>
          )
        })}
      </fieldset>
      <button
        type="button"
        className={styles.manual}
        aria-expanded={manual}
        aria-controls={`${id}-manual`}
        onClick={() => {
          setManual(true)
          requestAnimationFrame(() => {
            manualRef.current?.querySelector('input')?.focus()
            manualRef.current?.scrollIntoView?.({ block: 'nearest' })
          })
        }}
      >
        <ClockIcon size={20} />
        <span>
          <span className={styles.optionTitle}>Указать время вручную</span>
          <span className={styles.caption}>Задача закрепится, остальной день подстроится</span>
        </span>
        <ChevronRightIcon size={16} />
      </button>
      {manual ? (
        <div ref={manualRef} id={`${id}-manual`} className={styles.manualFields}>
          <TextField
            label="Дата начала"
            type="date"
            min={today}
            value={manualDate}
            onChange={(event) => setManualValue(`${event.target.value}T${manualTime}`)}
          />
          <TextField
            label="Время начала"
            type="time"
            step={60}
            value={manualTime}
            onChange={(event) => setManualValue(`${manualDate}T${event.target.value}`)}
          />
        </div>
      ) : null}
      <p className={styles.caption}>
        Выбранное время будет закреплено. При добавлении проверим доступность ещё раз. Часовой пояс:{' '}
        {context.timezone}.
      </p>
      <Button className={styles.confirm} disabled={!canSelect} onClick={apply}>
        {valid ? `Выбрать ${chosen.slice(11)}` : 'Выбрать время'}
      </Button>
    </section>
  )
}
