import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { paths } from '@/app/router/paths'
import { taskKeys } from '@/shared/api/planningKeys'
import type { DailySchedule } from '@/shared/model/schedule'
import type { Task } from '@/shared/model/task'
import { plannerExplanation } from '@/shared/lib/plannerText'
import { Button } from '@/shared/ui/button/Button'
import { useSessionStore } from '@/stores/session'
import { formatDate } from '@/pages/biorhythms/biorhythmChartModel'
import { transferProposals } from './todayTransferModel'
import { useTaskActions } from './useTaskActions'
import { timelineDuration } from './timelineModel'
import styles from './TodayDashboard.module.css'

type Proposal = ReturnType<typeof transferProposals>[number]

function MoveSuggestion({ day, proposal }: { day: DailySchedule; proposal: Proposal }) {
  const [dismissed, setDismissed] = useState(false)
  const generation = useSessionStore((state) => state.generation)
  const client = useQueryClient()
  const navigate = useNavigate()
  const actions = useTaskActions(
    proposal.task,
    day.schedule
      ? {
          ...day.schedule,
          planned_date: day.date,
          timezone: day.timezone,
        }
      : undefined,
    day.timezone,
  )
  if (dismissed)
    return (
      <p className={styles.transferText} role="status">
        Перенос отклонён. Сегодняшний план оставлен без изменений.
      </p>
    )
  return (
    <div className={styles.transfer}>
      <p className={styles.transferText}>
        Перенести «{proposal.task.title}» на{' '}
        {formatDate(proposal.date, { weekday: 'long', day: 'numeric', month: 'long' })}?{' '}
        {proposal.released > 0
          ? `Так сегодня освободится ${timelineDuration(proposal.released)}.`
          : 'Задача пока без времени. Перенос ещё не выполнен.'}
      </p>
      <details className={styles.hintDetails}>
        <summary>Почему так?</summary>
        <p>{plannerExplanation(proposal.explanation)}</p>
      </details>
      <p className={styles.transferCaution}>
        Предложение проверено при расчёте плана. Время на выбранный день не забронировано; при
        переносе расписание проверится заново.
      </p>
      {actions.notice ? (
        <p className={styles.transferError} role="status">
          {actions.notice}
        </p>
      ) : null}
      <div className={styles.transferActions}>
        <Button
          variant="secondary"
          size="s"
          disabled={actions.pending || actions.blocked}
          onClick={async () => {
            const saved = await actions.execute({ kind: 'recommend', date: proposal.date })
            if (!saved || useSessionStore.getState().generation !== generation) return
            const task = client.getQueryData<Task>(taskKeys.detail(generation, proposal.task.id))
            if (!task) return
            navigate(paths.today, {
              replace: true,
              state: {
                taskNotice: {
                  generation,
                  message: `«${task.title}» перенесена на ${formatDate(task.planned_date, { day: 'numeric', month: 'long' })}.${task.status === 'pending' ? ' Время пока не назначено.' : ''}`,
                },
              },
            })
          }}
        >
          {actions.pending
            ? 'Переносим…'
            : `Перенести на ${formatDate(proposal.date, { weekday: 'short', day: 'numeric' }).replace(',', '')}`}
        </Button>
        <Button
          variant="ghost"
          size="s"
          disabled={actions.pending}
          onClick={() => setDismissed(true)}
        >
          Оставить
        </Button>
        {actions.blocked ? (
          <Button
            variant="secondary"
            size="s"
            disabled={actions.pending}
            onClick={() => void actions.execute({ kind: 'refresh' })}
          >
            Обновить данные задачи
          </Button>
        ) : null}
      </div>
    </div>
  )
}

export function TodayLoadWarning({ day, now }: { day: DailySchedule; now: number }) {
  const proposals = transferProposals(day, now)
  if (!proposals.length)
    return (
      <p className={styles.transferText}>
        Проверенного предложения переноса пока нет. Можно изменить длительность или дату задачи
        вручную.
      </p>
    )
  return (
    <>
      {proposals.map((proposal) => (
        <MoveSuggestion key={proposal.key} day={day} proposal={proposal} />
      ))}
    </>
  )
}
