export function todayGreeting(now: Date, timezone: string, name?: string | null) {
  const hour = Number(
    new Intl.DateTimeFormat('en', { timeZone: timezone, hour: 'numeric', hourCycle: 'h23' }).format(
      now,
    ),
  )
  const greeting =
    hour < 5
      ? 'Доброй ночи'
      : hour < 12
        ? 'Доброе утро'
        : hour < 18
          ? 'Добрый день'
          : 'Добрый вечер'
  return name?.trim() ? `${greeting}, ${name.trim()}` : greeting
}

export function todayDateLabel(date: string) {
  const label = new Intl.DateTimeFormat('ru-RU', {
    timeZone: 'UTC',
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  }).format(new Date(`${date}T12:00:00Z`))
  return label.charAt(0).toUpperCase() + label.slice(1)
}

export function criticalDayCopy(dates: string[], today: string) {
  const list = new Intl.ListFormat('ru-RU', { style: 'long', type: 'conjunction' })
  const format = (date: string, options: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat('ru-RU', { ...options, timeZone: 'UTC' }).format(
      new Date(`${date}T12:00:00Z`),
    )
  const short = dates.map((date) =>
    date === today
      ? 'сегодня'
      : format(date, { weekday: 'short', day: 'numeric' }).replace(',', ''),
  )
  const sameMonth = dates.every((date) => date.slice(0, 7) === dates[0].slice(0, 7))
  const dateList = sameMonth
    ? `${list.format(dates.map((date) => String(Number(date.slice(8)))))} ${format(dates[0], { day: 'numeric', month: 'long' }).split(' ').slice(1).join(' ')}`
    : list.format(dates.map((date) => format(date, { day: 'numeric', month: 'long' })))
  const title =
    dates[0] === today
      ? dates.length === 1
        ? 'Сегодня критический день'
        : `Критические дни: ${list.format(short)}`
      : `${dates.length === 1 ? 'Впереди критический день' : 'Впереди критические дни'}: ${list.format(short)}`
  return {
    title,
    description: `${dates.length === 1 ? 'Отметка' : 'Отметки'} у нуля по модели — ${dateList}. Сверьтесь с самочувствием перед планированием.`,
  }
}
