function dateTimeFormatter(timezone: string) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  })
}

function formattedDateTime(formatter: Intl.DateTimeFormat, instant: number) {
  const parts = formatter.formatToParts(new Date(instant))
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)!.value
  return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}:${part('second')}`
}

export function localDate(instant: Date, timezone: string): string {
  return formattedDateTime(dateTimeFormatter(timezone), instant.getTime()).slice(0, 10)
}

export function localDateTime(instant: Date, timezone: string): string {
  return formattedDateTime(dateTimeFormatter(timezone), instant.getTime()).slice(0, 16)
}

export function isCalendarDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const instant = Date.parse(`${value}T00:00:00Z`)
  return Number.isFinite(instant) && new Date(instant).toISOString().slice(0, 10) === value
}

export type LocalDateTimeResult =
  { status: 'valid'; instant: number } | { status: 'invalid' | 'nonexistent' | 'ambiguous' }

export function resolveLocalDateTime(value: string, timezone: string): LocalDateTimeResult {
  if (
    !/^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):[0-5]\d$/.test(value) ||
    !isCalendarDate(value.slice(0, 10))
  )
    return { status: 'invalid' }

  const formatter = dateTimeFormatter(timezone)
  const wallTime = Date.parse(`${value}:00Z`)
  const offsets = new Set<number>()
  for (let hours = -36; hours <= 36; hours += 6) {
    const probe = wallTime + hours * 3_600_000
    offsets.add(Date.parse(`${formattedDateTime(formatter, probe)}Z`) - probe)
  }
  const matches = [...offsets]
    .map((offset) => wallTime - offset)
    .filter((instant) => formattedDateTime(formatter, instant) === `${value}:00`)
  if (matches.length === 0) return { status: 'nonexistent' }
  if (matches.length > 1) return { status: 'ambiguous' }
  return { status: 'valid', instant: matches[0] }
}
