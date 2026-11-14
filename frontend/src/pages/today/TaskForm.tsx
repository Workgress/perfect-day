import { useEffect, useId, useRef, useState, useSyncExternalStore, type FormEvent } from 'react'
import { cx } from '@/shared/lib/cx'
import { localDate } from '@/shared/lib/dateTime'
import {
  TASK_TYPES,
  type TaskCreateRequest,
  type TaskFormValues,
  type TaskPriority,
  type TaskType,
} from '@/shared/model/task'
import { Button } from '@/shared/ui/button/Button'
import { SelectField, TextAreaField, TextField } from '@/shared/ui/form-field/FormField'
import {
  BellIcon,
  CalendarIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  ClockIcon,
  LockIcon,
  PlusIcon,
  SparklesIcon,
  XIcon,
} from '@/shared/ui/icon/icons'
import * as Segment from '@/shared/ui/segment/Segment'
import { Toggle } from '@/shared/ui/toggle/Toggle'
import {
  DURATION_PRESETS,
  TASK_TYPE_HINTS,
  emptyTaskForm,
  prepareTaskForm,
  type TaskFormContext,
  type TaskFormErrors,
} from './taskFormModel'
import styles from './TaskForm.module.css'
import {
  emptyTaskSettings,
  prepareTaskSettings,
  REMINDER_OPTIONS,
  REPEAT_OPTIONS,
  WEEKDAYS,
  type TaskFormOptions,
  type TaskFormSettings,
  type TaskSettingsErrors,
} from './taskFormSettings'

export type TaskTimeSuggestion = {
  startsAt: string
  endsAt: string
  explanation: string
}

type TaskFormProps = {
  context: TaskFormContext
  initialValues?: TaskFormValues
  onCancel: () => void
  onSubmit: (request: TaskCreateRequest, options: TaskFormOptions) => void
  preview?: TaskCreateRequest | null
  previewOptions?: TaskFormOptions | null
  initialSettings?: TaskFormSettings
  suggestion?: TaskTimeSuggestion | null
  onChange?: () => void
}

type DateTimeFieldProps = {
  label: string
  dateLabel: string
  timeLabel: string
  value: string
  onChange: (value: string) => void
  onBlur: () => void
  onClear?: () => void
  min: string
  field: 'deadlineLocal' | 'pinnedStartLocal'
  error?: string
  required?: boolean
}

function DateTimeField({
  label,
  dateLabel,
  timeLabel,
  value,
  onChange,
  onBlur,
  onClear,
  min,
  field,
  error,
  required,
}: DateTimeFieldProps) {
  const id = useId()
  const [date = '', time = ''] = value.split('T')
  const change = (nextDate: string, nextTime: string) =>
    onChange(nextDate || nextTime ? `${nextDate}T${nextTime}` : '')

  return (
    <fieldset
      className={styles.field}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) onBlur()
      }}
    >
      <legend className={styles.label}>
        {label} <span>{required ? 'обязательно' : 'необязательно'}</span>
      </legend>
      <div className={styles.dateTime}>
        <TextField
          label={dateLabel}
          name={`${field}Date`}
          data-field={field}
          type="date"
          min={min}
          value={date}
          required={required}
          aria-invalid={Boolean(error) && (!date || Boolean(time))}
          aria-describedby={error ? `${id}-error` : undefined}
          onChange={(event) => change(event.target.value, time)}
        />
        <TextField
          label={timeLabel}
          name={`${field}Time`}
          data-field={field}
          type="time"
          step={60}
          value={time}
          required={required}
          aria-invalid={Boolean(error) && (!time || Boolean(date))}
          aria-describedby={error ? `${id}-error` : undefined}
          onChange={(event) => change(date, event.target.value)}
        />
        {!required && value ? (
          <Button
            variant="ghost"
            size="s"
            className={styles.clearDate}
            aria-label="Очистить дедлайн"
            onClick={() => {
              onChange('')
              onClear?.()
            }}
          >
            <XIcon />
          </Button>
        ) : null}
      </div>
      {error ? (
        <p id={`${id}-error`} className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
    </fieldset>
  )
}

const PRIORITIES: { value: TaskPriority; label: string }[] = [
  { value: 'high', label: 'Высокий' },
  { value: 'medium', label: 'Средний' },
  { value: 'low', label: 'Низкий' },
]
const TYPE_ORDER: TaskType[] = ['intellectual', 'creative', 'physical', 'routine']

function subscribeToLayout(onChange: () => void) {
  const media = window.matchMedia('(max-width: 768px)')
  media.addEventListener('change', onChange)
  return () => media.removeEventListener('change', onChange)
}

function mobileSnapshot() {
  return window.matchMedia('(max-width: 768px)').matches
}

export function TaskForm({
  context,
  initialValues,
  onCancel,
  onSubmit,
  preview,
  previewOptions,
  initialSettings,
  suggestion,
  onChange,
}: TaskFormProps) {
  const [values, setValues] = useState(
    () => initialValues ?? emptyTaskForm(context.timezone, context.now),
  )
  const mobile = useSyncExternalStore(subscribeToLayout, mobileSnapshot, () => false)
  const [submitted, setSubmitted] = useState(false)
  const [clock, setClock] = useState(() => context.now ?? new Date())
  const [touched, setTouched] = useState<Partial<Record<keyof TaskFormValues, boolean>>>({})
  const [nativeErrors, setNativeErrors] = useState<TaskFormErrors>({})
  const [expanded, setExpanded] = useState(false)
  const [settings, setSettings] = useState(() => initialSettings ?? emptyTaskSettings())
  const [settingsErrors, setSettingsErrors] = useState<TaskSettingsErrors>({})
  const [hasDeadline, setHasDeadline] = useState(Boolean(values.deadlineLocal))
  const [hasPreferredTime, setHasPreferredTime] = useState(Boolean(values.preferredStart))
  const [customDuration, setCustomDuration] = useState(
    values.durationMin !== '' &&
      !DURATION_PRESETS.some((item) => item.value === values.durationMin),
  )
  const formRef = useRef<HTMLFormElement>(null)
  const previewRef = useRef<HTMLElement>(null)
  const dirtyFields = useRef(new Set<keyof TaskFormValues>())
  const id = useId()
  const errors = { ...prepareTaskForm(values, { ...context, now: clock }).errors, ...nativeErrors }
  const today = localDate(clock, context.timezone)
  const updateSetting = <K extends keyof TaskFormSettings>(
    field: K,
    value: TaskFormSettings[K],
  ) => {
    setSettings((current) => ({ ...current, [field]: value }))
    setSettingsErrors((current) => ({ ...current, [field]: undefined }))
    onChange?.()
  }
  const formatMoment = (value: string) =>
    new Intl.DateTimeFormat('ru-RU', {
      timeZone: context.timezone,
      day: 'numeric',
      month: 'long',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(value))

  useEffect(() => {
    if (!preview) return
    previewRef.current?.focus()
    previewRef.current?.scrollIntoView?.({ block: 'nearest' })
  }, [preview])
  const error = (field: keyof TaskFormValues) =>
    submitted || touched[field] ? errors[field] : undefined
  const touch = (field: keyof TaskFormValues) => {
    if (submitted || dirtyFields.current.has(field))
      setTouched((current) => ({ ...current, [field]: true }))
  }
  const update = <K extends keyof TaskFormValues>(field: K, value: TaskFormValues[K]) => {
    dirtyFields.current.add(field)
    setValues((current) => ({
      ...current,
      [field]: value,
      ...(field === 'isPinned' && !value ? { pinnedStartLocal: '' } : {}),
      ...(field === 'plannedDate' && current.pinnedStartLocal
        ? { pinnedStartLocal: `${value}T${current.pinnedStartLocal.split('T')[1] ?? ''}` }
        : {}),
    }))
    setNativeErrors((current) => {
      const next = { ...current }
      delete next[field]
      return next
    })
    onChange?.()
  }

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const currentClock = context.now ?? new Date()
    setClock(currentClock)
    const result = prepareTaskForm(values, { ...context, now: currentClock })
    if (hasDeadline && !values.deadlineLocal)
      result.errors.deadlineLocal = 'Укажите дату и время полностью.'
    if (hasPreferredTime && !values.preferredStart)
      result.errors.preferredStart = 'Укажите время или выберите «Не важно — подберём сами».'
    const settingsResult = prepareTaskSettings(settings, values.plannedDate)
    formRef.current?.querySelectorAll<HTMLInputElement>('input[data-setting]').forEach((input) => {
      if (input.validity.badInput)
        settingsResult.errors[input.dataset.setting as keyof TaskFormSettings] =
          'Заполните поле полностью.'
    })
    const invalid: TaskFormErrors = {}
    formRef.current?.querySelectorAll<HTMLInputElement>('input[data-field]').forEach((input) => {
      if (input.validity.badInput)
        invalid[input.dataset.field as keyof TaskFormValues] = 'Заполните поле полностью.'
    })
    setNativeErrors(invalid)
    setSettingsErrors(settingsResult.errors)
    setSubmitted(true)
    if (Object.keys({ ...result.errors, ...invalid, ...settingsResult.errors }).length) {
      if (
        result.errors.priority ||
        result.errors.preferredStart ||
        result.errors.plannedDate ||
        (mobile && result.errors.pinnedStartLocal) ||
        Object.keys(settingsResult.errors).length
      )
        setExpanded(true)
      requestAnimationFrame(() => {
        const invalidField = Array.from(
          formRef.current?.querySelectorAll<HTMLElement>('[aria-invalid="true"]') ?? [],
        ).find((field) => !field.closest('[hidden]'))
        const control = invalidField?.matches('input, textarea, select, button')
          ? invalidField
          : invalidField?.querySelector<HTMLElement>('input, textarea, select, button')
        control?.focus()
        control?.scrollIntoView?.({ block: 'nearest' })
      })
      return
    }
    if (result.request && settingsResult.options) onSubmit(result.request, settingsResult.options)
  }

  const titleField = (
    <TextField
      className={styles.title}
      label="Название"
      name="title"
      data-field="title"
      placeholder="Что нужно сделать?"
      value={values.title}
      required
      autoComplete="off"
      error={error('title')}
      onChange={(event) => update('title', event.target.value)}
      onBlur={() => touch('title')}
    />
  )

  const descriptionField = (
    <TextAreaField
      className={styles.description}
      label="Описание · необязательно"
      name="description"
      placeholder="Пара слов для себя"
      rows={1}
      value={values.description}
      onChange={(event) => update('description', event.target.value)}
    />
  )

  const durationField = (
    <fieldset className={cx(styles.field, styles.duration)}>
      <legend id={`${id}-duration-label`} className={styles.label}>
        Длительность <span>обязательно</span>
      </legend>
      <Segment.Root
        aria-labelledby={`${id}-duration-label`}
        aria-required="true"
        aria-invalid={Boolean(error('durationMin'))}
        aria-describedby={error('durationMin') ? `${id}-duration-error` : undefined}
        className={styles.chips}
        value={customDuration ? 'custom' : String(values.durationMin)}
        onValueChange={(value) => {
          const custom = value === 'custom'
          setCustomDuration(custom)
          update('durationMin', custom ? '' : Number(value))
          if (custom)
            requestAnimationFrame(() =>
              formRef.current?.querySelector<HTMLInputElement>('[name="durationMin"]')?.focus(),
            )
        }}
      >
        {DURATION_PRESETS.map((item, index) => (
          <Segment.Item
            key={item.value}
            value={String(item.value)}
            className={styles.chip}
            {...(values.durationMin === '' && !customDuration && index === 0
              ? { tabIndex: 0 }
              : {})}
          >
            {item.label}
          </Segment.Item>
        ))}
        <Segment.Item value="custom" className={styles.chip}>
          Другое…
        </Segment.Item>
      </Segment.Root>
      {customDuration ? (
        <TextField
          label="Длительность в минутах"
          name="durationMin"
          data-field="durationMin"
          type="number"
          inputMode="numeric"
          min={5}
          max={480}
          step={1}
          required
          value={values.durationMin}
          hint="От 5 до 480 минут"
          aria-invalid={Boolean(error('durationMin'))}
          aria-describedby={error('durationMin') ? `${id}-duration-error` : undefined}
          onChange={(event) =>
            update('durationMin', event.target.value === '' ? '' : Number(event.target.value))
          }
          onBlur={() => touch('durationMin')}
        />
      ) : null}
      {error('durationMin') ? (
        <p id={`${id}-duration-error`} className={styles.error} role="alert">
          {error('durationMin')}
        </p>
      ) : null}
    </fieldset>
  )

  const typeField = (
    <fieldset className={cx(styles.field, styles.type)}>
      <legend id={`${id}-type-label`} className={styles.label}>
        Тип <span>обязательно</span>
      </legend>
      <Segment.Root
        value={values.type}
        onValueChange={(value) => update('type', value as TaskType)}
        className={styles.chips}
        aria-labelledby={`${id}-type-label`}
        aria-required="true"
        aria-invalid={Boolean(error('type'))}
        aria-describedby={`${id}-type-hint${error('type') ? ` ${id}-type-error` : ''}`}
      >
        {TYPE_ORDER.map((type, index) => (
          <Segment.Item
            key={type}
            value={type}
            className={styles.typeChip}
            data-type={type}
            {...(!values.type && index === 0 ? { tabIndex: 0 } : {})}
          >
            <span className={styles.dot} aria-hidden="true" />
            {TASK_TYPES[type]}
          </Segment.Item>
        ))}
      </Segment.Root>
      <p id={`${id}-type-hint`} className={styles.hint}>
        {values.type
          ? TASK_TYPE_HINTS[values.type]
          : 'От типа зависит время: учёба — на пик интеллектуального цикла, спорт — физического, творчество и общение — эмоционального.'}
      </p>
      {error('type') ? (
        <p id={`${id}-type-error`} className={styles.error} role="alert">
          {error('type')}
        </p>
      ) : null}
    </fieldset>
  )

  const deadlineField = (
    <div className={styles.dates}>
      <SelectField
        label="Срок · необязательно"
        name="deadlineMode"
        leadingIcon={<CalendarIcon size={18} />}
        value={hasDeadline ? 'date' : 'none'}
        onChange={(event) => {
          const enabled = event.target.value === 'date'
          setHasDeadline(enabled)
          if (!enabled) update('deadlineLocal', '')
        }}
      >
        <option value="none">Без срока</option>
        <option value="date">Указать дату и время</option>
      </SelectField>
      {hasDeadline ? (
        <DateTimeField
          label="Дата и время дедлайна"
          dateLabel="Дата дедлайна"
          timeLabel="Время дедлайна"
          field="deadlineLocal"
          value={values.deadlineLocal}
          min={values.plannedDate || today}
          error={error('deadlineLocal')}
          onChange={(value) => update('deadlineLocal', value)}
          onClear={() => setHasDeadline(false)}
          onBlur={() => touch('deadlineLocal')}
        />
      ) : null}
    </div>
  )

  const repeatField = (
    <fieldset className={styles.field}>
      <legend id={`${id}-repeat-label`} className={styles.label}>
        Повторять
      </legend>
      <Segment.Root
        value={settings.repeat}
        onValueChange={(value) => updateSetting('repeat', value as TaskFormSettings['repeat'])}
        aria-labelledby={`${id}-repeat-label`}
        aria-invalid={Boolean(settingsErrors.repeat)}
        aria-describedby={`${id}-repeat-hint${settingsErrors.repeat ? ` ${id}-repeat-error` : ''}`}
        className={mobile ? styles.chips : styles.repeatOptions}
      >
        {REPEAT_OPTIONS.map((item) => (
          <Segment.Item
            key={item.value}
            value={item.value}
            className={mobile ? styles.chip : undefined}
          >
            {item.label}
          </Segment.Item>
        ))}
      </Segment.Root>
      <p id={`${id}-repeat-hint`} className={styles.hint}>
        Повторяющиеся задачи тоже раскладываются по циклам: каждое вхождение ставится в своё лучшее
        окно.
      </p>
      {settingsErrors.repeat ? (
        <p id={`${id}-repeat-error`} role="alert" className={styles.error}>
          {settingsErrors.repeat}
        </p>
      ) : null}
      {settings.repeat === 'custom' ? (
        <div className={styles.customSchedule}>
          <TextField
            label="Интервал в неделях"
            name="repeatInterval"
            data-setting="repeatInterval"
            type="number"
            min={1}
            max={52}
            step={1}
            required
            value={settings.repeatInterval}
            error={settingsErrors.repeatInterval}
            onChange={(event) =>
              updateSetting(
                'repeatInterval',
                event.target.value === '' ? '' : Number(event.target.value),
              )
            }
          />
          <fieldset
            className={styles.field}
            aria-describedby={settingsErrors.repeatDays ? `${id}-days-error` : undefined}
          >
            <legend className={styles.label}>Дни недели</legend>
            <div className={styles.weekdays}>
              {WEEKDAYS.map((day, index) => (
                <label key={day} className={styles.weekday}>
                  <input
                    type="checkbox"
                    checked={settings.repeatDays.includes(index + 1)}
                    aria-invalid={Boolean(settingsErrors.repeatDays)}
                    aria-describedby={settingsErrors.repeatDays ? `${id}-days-error` : undefined}
                    onChange={(event) =>
                      updateSetting(
                        'repeatDays',
                        event.target.checked
                          ? [...settings.repeatDays, index + 1]
                          : settings.repeatDays.filter((value) => value !== index + 1),
                      )
                    }
                  />
                  <span>{day}</span>
                </label>
              ))}
            </div>
            {settingsErrors.repeatDays ? (
              <p id={`${id}-days-error`} role="alert" className={styles.error}>
                {settingsErrors.repeatDays}
              </p>
            ) : null}
          </fieldset>
          <TextField
            label="Повторять до · необязательно"
            name="repeatUntil"
            data-setting="repeatUntil"
            type="date"
            min={values.plannedDate || today}
            value={settings.repeatUntil}
            error={settingsErrors.repeatUntil}
            onChange={(event) => updateSetting('repeatUntil', event.target.value)}
          />
        </div>
      ) : null}
    </fieldset>
  )

  const pinField = (
    <div className={styles.pinning}>
      <div className={styles.pinRow}>
        {!mobile ? <LockIcon size={18} /> : null}
        <div>
          <p id={`${id}-pin-label`} className="text-label">
            Закрепить время
          </p>
          <p id={`${id}-pin-hint`} className={styles.hint}>
            Алгоритм не будет сдвигать задачу при пересчёте дня
          </p>
        </div>
        <Toggle
          checked={values.isPinned}
          aria-labelledby={`${id}-pin-label`}
          aria-describedby={`${id}-pin-hint`}
          onCheckedChange={(checked) => {
            update('isPinned', checked)
            if (checked && !values.pinnedStartLocal)
              setValues((current) => ({ ...current, pinnedStartLocal: `${current.plannedDate}T` }))
          }}
        />
      </div>
      {values.isPinned ? (
        <DateTimeField
          label="Начало задачи"
          dateLabel="Дата закрепления"
          timeLabel="Время закрепления"
          field="pinnedStartLocal"
          value={values.pinnedStartLocal}
          min={today}
          required
          error={error('pinnedStartLocal')}
          onChange={(value) => {
            update('pinnedStartLocal', value)
            if (value.slice(0, 10)) update('plannedDate', value.slice(0, 10))
          }}
          onBlur={() => touch('pinnedStartLocal')}
        />
      ) : null}
    </div>
  )

  const priorityField = (
    <fieldset className={styles.field}>
      <legend id={`${id}-priority-label`} className={styles.label}>
        Приоритет
      </legend>
      <Segment.Root
        value={values.priority}
        onValueChange={(value) => update('priority', value as TaskPriority)}
        aria-labelledby={`${id}-priority-label`}
        className={styles.priorities}
      >
        {PRIORITIES.map((item) => (
          <Segment.Item key={item.value} value={item.value}>
            {item.label}
          </Segment.Item>
        ))}
      </Segment.Root>
    </fieldset>
  )

  const preferredField = (
    <div className={styles.field}>
      <SelectField
        label="Желаемое время · необязательно"
        name="preferredMode"
        leadingIcon={<ClockIcon size={18} />}
        value={hasPreferredTime ? 'time' : 'auto'}
        onChange={(event) => {
          const enabled = event.target.value === 'time'
          setHasPreferredTime(enabled)
          if (!enabled) update('preferredStart', '')
        }}
      >
        <option value="auto">Не важно — подберём сами</option>
        <option value="time">Указать время</option>
      </SelectField>
      {hasPreferredTime || error('plannedDate') || error('preferredStart') ? (
        <div className={styles.preferredFields}>
          <TextField
            label="День задачи"
            name="plannedDate"
            data-field="plannedDate"
            type="date"
            required
            min={today}
            value={values.plannedDate}
            error={error('plannedDate')}
            onChange={(event) => update('plannedDate', event.target.value)}
            onBlur={() => touch('plannedDate')}
          />
          <TextField
            label="Время начала"
            name="preferredStart"
            data-field="preferredStart"
            type="time"
            step={60}
            value={values.preferredStart}
            error={error('preferredStart')}
            hint={`Рабочий день: ${context.workStart}–${context.workEnd}. Часовой пояс: ${context.timezone}.`}
            onChange={(event) => update('preferredStart', event.target.value)}
            onBlur={() => touch('preferredStart')}
          />
        </div>
      ) : null}
    </div>
  )

  const reminderField = (
    <SelectField
      label="Напоминание"
      name="reminder"
      leadingIcon={<BellIcon size={18} />}
      value={settings.reminder}
      error={settingsErrors.reminder}
      onChange={(event) => updateSetting('reminder', event.target.value)}
    >
      {REMINDER_OPTIONS.map((item) => (
        <option key={item.value} value={item.value}>
          {item.label}
        </option>
      ))}
    </SelectField>
  )

  return (
    <form
      ref={formRef}
      className={styles.form}
      noValidate
      onSubmit={submit}
      aria-label="Создание задачи"
    >
      <div className={styles.body}>
        {titleField}
        {mobile ? typeField : descriptionField}
        {durationField}
        {mobile ? null : typeField}
        {deadlineField}
        {!mobile ? (
          <>
            {repeatField}
            {pinField}
          </>
        ) : null}
        <div className={styles.additional}>
          <button
            type="button"
            className={styles.disclosure}
            aria-expanded={expanded}
            aria-controls={`${id}-additional`}
            onClick={() => setExpanded((current) => !current)}
          >
            <ChevronDownIcon size={mobile ? 18 : 16} />
            <span>
              {mobile
                ? 'Дополнительно'
                : `${expanded ? 'Свернуть' : 'Ещё'}: приоритет, время, напоминание`}
              {mobile && !expanded ? (
                <span className={styles.disclosureHint}>
                  Приоритет, желаемое время, повтор, закрепление
                </span>
              ) : null}
            </span>
          </button>
          <div id={`${id}-additional`} className={styles.additionalFields} hidden={!expanded}>
            {priorityField}
            {preferredField}
            {mobile ? (
              <>
                {repeatField}
                {pinField}
              </>
            ) : null}
            {reminderField}
            {mobile ? descriptionField : null}
          </div>
        </div>
        <section
          className={cx(styles.suggestion, suggestion && styles.hasSuggestion)}
          aria-label="Предложенное время"
        >
          <SparklesIcon size={16} />
          <div>
            {suggestion ? (
              <>
                <p className="text-label">
                  Предложим {formatMoment(suggestion.startsAt)}–
                  {new Intl.DateTimeFormat('ru-RU', {
                    timeZone: context.timezone,
                    hour: '2-digit',
                    minute: '2-digit',
                  }).format(new Date(suggestion.endsAt))}
                </p>
                <p className={styles.suggestionText}>{suggestion.explanation}</p>
                <button
                  type="button"
                  className={styles.chooseTime}
                  onClick={() => {
                    setExpanded(true)
                    setHasPreferredTime(true)
                    requestAnimationFrame(() =>
                      formRef.current
                        ?.querySelector<HTMLInputElement>('[name="preferredStart"]')
                        ?.focus(),
                    )
                  }}
                >
                  Выбрать другое время <ChevronRightIcon size={14} />
                </button>
              </>
            ) : (
              <>
                {!mobile ? <p className="text-label">Подберём лучшее окно</p> : null}
                <p className={styles.suggestionText}>
                  {values.title.trim() && values.type && values.durationMin
                    ? 'Время ещё не рассчитано. Подберём окно по вашим биоритмам и хронотипу и покажем изменения перед применением.'
                    : 'Укажите название, тип и длительность — подберём лучшее окно по вашим биоритмам и хронотипу.'}
                </p>
              </>
            )}
          </div>
        </section>
        {preview ? (
          <section
            ref={previewRef}
            tabIndex={-1}
            className={styles.preview}
            aria-label="Проверка задачи"
            role="status"
          >
            <CheckIcon size={18} />
            <div>
              <p className="text-label">Данные задачи проверены</p>
              <p className={styles.previewTitle}>{preview.title}</p>
              <p className={styles.hint}>
                {TASK_TYPES[preview.type]} · {preview.duration_min} мин ·{' '}
                {PRIORITIES.find((item) => item.value === preview.priority)?.label} приоритет
              </p>
              <p className={styles.hint}>
                День задачи: {preview.planned_date.split('-').reverse().join('.')}
              </p>
              {preview.deadline ? (
                <p className={styles.hint}>Дедлайн: {formatMoment(preview.deadline)}</p>
              ) : null}
              {preview.is_pinned ? (
                <p className={styles.hint}>Закреплено: {formatMoment(preview.pinned_start)}</p>
              ) : null}
              {previewOptions?.recurrence ? (
                <p className={styles.hint}>
                  Повтор:{' '}
                  {previewOptions.recurrence.frequency === 'daily'
                    ? 'каждый день'
                    : `каждые ${previewOptions.recurrence.interval} нед. · ${previewOptions.recurrence.weekdays.map((day) => WEEKDAYS[day - 1]).join(', ')}`}
                  {previewOptions.recurrence.until
                    ? ` · до ${previewOptions.recurrence.until.split('-').reverse().join('.')}`
                    : ''}
                </p>
              ) : null}
              {previewOptions ? (
                <p className={styles.hint}>
                  {
                    REMINDER_OPTIONS.find(
                      (item) =>
                        item.value ===
                        (previewOptions.reminderMinutes === null
                          ? ''
                          : String(previewOptions.reminderMinutes)),
                    )?.label
                  }
                </p>
              ) : null}
              <p className={styles.hint}>Задача ещё не добавлена в план.</p>
            </div>
          </section>
        ) : null}
      </div>
      <footer className={styles.actions}>
        <Button variant="ghost" className={styles.cancel} onClick={onCancel}>
          Отмена
        </Button>
        <Button
          type="submit"
          className={styles.submit}
          disabled={!values.title.trim() || !values.type || values.durationMin === ''}
        >
          {mobile ? <SparklesIcon size={18} /> : <PlusIcon size={18} />}
          Добавить и распределить
        </Button>
        {mobile ? (
          <p className={styles.actionHint}>Перед применением покажем, что изменится в плане.</p>
        ) : null}
      </footer>
    </form>
  )
}
