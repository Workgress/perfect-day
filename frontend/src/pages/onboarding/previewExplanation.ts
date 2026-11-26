// The preview API also serves diagnostic copy from older planner versions.
// Adapt only that known format; keep local and unfamiliar explanations intact.
export function previewExplanation(explanation: string) {
  const clock = /^\d{2}:\d{2}(?: [+-]\d{4})?–\d{2}:\d{2}(?: [+-]\d{4})?\.\s*/u
  if (!clock.test(explanation)) return explanation

  const text = explanation
    .replace(clock, '')
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

  return text || explanation
}
