import { CHRONOTYPES, chronotypePeak, dayTicks, dayWindows } from './chronotype'
import { formatTime } from './model'

describe('chronotype windows', () => {
  it.each([
    ['lark', '08:00–11:00'],
    ['dove', '09:00–12:00'],
    ['owl', '12:00–15:00'],
  ] as const)('preserves the original peak label on the %s card', (type, peak) => {
    expect(chronotypePeak(type)).toBe(peak)
  })

  it('clips a partially visible peak without moving it to an earlier time', () => {
    expect(dayWindows('owl', '15:30', '18:00')[0]).toMatchObject({
      label: 'Интеллектуальное окно · пик 14–16',
      start: 930,
      end: 960,
    })
  })

  it.each([
    [
      'dove',
      '09:00',
      '19:00',
      '23:30',
      [
        [540, 660],
        [660, 780],
        [780, 840],
        [840, 930],
        [960, 1020],
        [1020, 1140],
      ],
    ],
    [
      'owl',
      '12:00',
      '22:00',
      '01:00',
      [
        [720, 840],
        [840, 960],
        [960, 1020],
        [1020, 1110],
        [1140, 1200],
        [1200, 1320],
      ],
    ],
  ] as const)(
    'uses the complete supplied %s schedule and default hours',
    (type, workStart, workEnd, sleepTime, intervals) => {
      expect(CHRONOTYPES.find((item) => item.value === type)).toMatchObject({
        workStart,
        workEnd,
        sleepTime,
      })
      expect(dayWindows(type, workStart, workEnd).map(({ start, end }) => [start, end])).toEqual(
        intervals,
      )
    },
  )

  it.each(['lark', 'dove', 'owl'] as const)(
    'keeps windows inside the chosen day without overlaps for %s',
    (type) => {
      const windows = dayWindows(type, '05:30', '23:30')
      expect(windows[0].start).toBe(330)
      expect(windows.at(-1)?.end).toBe(1410)
      windows.forEach((window, index) => {
        expect(window.end).toBeGreaterThan(window.start)
        expect(window.start).toBeGreaterThanOrEqual(330)
        expect(window.end).toBeLessThanOrEqual(1410)
        if (index) expect(window.start).toBeGreaterThanOrEqual(windows[index - 1].end)
      })
    },
  )

  it.each(['lark', 'dove', 'owl'] as const)(
    'leaves exactly thirty empty minutes before the physical window for %s',
    (type) => {
      const windows = dayWindows(type, '00:00', '23:30')
      const index = windows.findIndex((window) => window.type === 'physical')
      expect(windows[index].end - windows[index].start).toBe(60)
      expect(windows[index].start - windows[index - 1].end).toBe(30)
      expect(
        dayWindows(type, formatTime(windows[index].start - 30), formatTime(windows[index].start)),
      ).toEqual([])
    },
  )

  it('shows routine when all activity peaks fall outside a short working window', () => {
    expect(dayWindows('owl', '08:00', '08:30')).toEqual([
      { type: 'routine', label: 'Спокойные дела и рутина', start: 480, end: 510 },
    ])
  })

  it.each([
    ['18:00', '08:00'],
    ['08:00', '08:00'],
    ['25:00', '26:00'],
  ])('does not generate windows for an invalid day %s–%s', (start, end) => {
    expect(dayWindows('lark', start, end)).toEqual([])
  })

  it('keeps half-hour boundaries and whole hours on the time axis', () => {
    expect(dayTicks(510, 660)).toEqual([510, 540, 600, 660])
    expect(dayTicks(480, 510)).toEqual([480, 510])
  })
})
