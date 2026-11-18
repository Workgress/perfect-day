import { isCalendarDate, localDate, resolveLocalDateTime } from './dateTime'

describe('profile timezone dates', () => {
  it('uses the profile calendar day across UTC midnight', () => {
    expect(localDate(new Date('2026-11-11T21:00:00Z'), 'Asia/Yekaterinburg')).toBe('2026-11-12')
    expect(localDate(new Date('2026-11-11T01:00:00Z'), 'America/New_York')).toBe('2026-11-10')
  })

  it.each(['2026-02-29', '2026-02-31', '2026-13-01', '2026-11-11T12:00'])(
    'rejects invalid calendar date %s',
    (value) => {
      expect(isCalendarDate(value)).toBe(false)
    },
  )

  it('converts local date and time without using the computer timezone', () => {
    expect(resolveLocalDateTime('2026-11-11T14:00', 'Asia/Yekaterinburg')).toEqual({
      status: 'valid',
      instant: Date.parse('2026-11-11T09:00:00Z'),
    })
    expect(resolveLocalDateTime('2026-11-11T14:00', 'Asia/Kathmandu')).toEqual({
      status: 'valid',
      instant: Date.parse('2026-11-11T08:15:00Z'),
    })
  })

  it('rejects skipped and repeated local times during DST', () => {
    expect(resolveLocalDateTime('2027-03-28T02:30', 'Europe/Berlin')).toEqual({
      status: 'nonexistent',
    })
    expect(resolveLocalDateTime('2027-10-31T02:30', 'Europe/Berlin')).toEqual({
      status: 'ambiguous',
    })
    expect(resolveLocalDateTime('2027-03-28T03:30', 'Europe/Berlin')).toEqual({
      status: 'valid',
      instant: Date.parse('2027-03-28T01:30:00Z'),
    })
  })
})
