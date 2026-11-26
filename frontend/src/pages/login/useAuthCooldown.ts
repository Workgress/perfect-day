import { useEffect, useState } from 'react'

export function useAuthCooldown(initialSeconds = 0) {
  const [until, setUntil] = useState(() => Date.now() + Math.max(0, initialSeconds) * 1000)
  const [seconds, setSeconds] = useState(Math.max(0, initialSeconds))
  useEffect(() => {
    const update = () => setSeconds(Math.max(0, Math.ceil((until - Date.now()) / 1000)))
    update()
    const timer = window.setInterval(update, 1000)
    window.addEventListener('focus', update)
    document.addEventListener('visibilitychange', update)
    return () => {
      clearInterval(timer)
      window.removeEventListener('focus', update)
      document.removeEventListener('visibilitychange', update)
    }
  }, [until])
  return {
    seconds,
    start: (value: number) => {
      const next = Math.max(0, Math.ceil(value))
      setSeconds(next)
      setUntil(Date.now() + next * 1000)
    },
  }
}

export function cooldownLabel(seconds: number) {
  return `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`
}
