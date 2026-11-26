// Planner text already uses the profile's local clocks. Hide a repeated offset,
// but retain explicit UTC offsets when a DST transition makes clocks ambiguous.
export function plannerMessage(text: string) {
  const clock = /\b(\d{2}:\d{2})\s+([+−-]\d{2}:?\d{2})\b/gu
  const offsets = new Set(
    [...text.matchAll(clock)].map((match) => match[2].replace('−', '-').replace(':', '')),
  )
  return text.replace(clock, (_match, time: string, offset: string) => {
    if (offsets.size <= 1) return time
    const normalized = offset.replace('−', '-').replace(':', '')
    return `${time} (UTC${normalized.slice(0, 3)}:${normalized.slice(3)})`
  })
}

// Compact the known diagnostic format without deriving new reasons or phases.
// Unknown explanations and constraints (including deadlines) stay intact.
export function plannerExplanation(explanation: string) {
  const text = plannerMessage(explanation)
    .replace(/(^|\.\s+)\d{2}:\d{2}–\d{2}:\d{2}\.\s*/gu, '$1')
    .replace(
      'Время выбрано по оценке энергии и ограничениям расписания.',
      'Учтены биоритмы, режим дня и свободное время.',
    )
    .replace(
      'Рутинная задача размещена с предпочтением менее энергичных окон.',
      'Для рутины выбрано менее энергичное окно.',
    )
    .replace(
      'Интервал включает высокое окно суточного профиля энергии.',
      'Время подходит по суточному ритму вашего хронотипа.',
    )
    .replace('Начало закреплено пользователем.', 'Время закреплено вами.')
    .replace(
      /(Интеллектуальный|Физический|Эмоциональный) биоритм: среднее за интервал ([+−-]?\d+(?:[.,]\d+)?)%\./u,
      (_match, cycle: string, value: string) =>
        `${cycle} биоритм за это время: ${value.replace('-', '−').replace('.', ',')} %.`,
    )
    .replace('Среднее значение биоритма находится в фазе пика.', '')
    .replace(/Среднее значение суточного профиля: \d+(?:[.,]\d+)?% \(хронотип: [^)]+\)\./u, '')
    .replace(/Длительность: \d+ мин\./u, '')
    .replace(/\s+/gu, ' ')
    .trim()
  return text || plannerMessage(explanation).trim()
}
