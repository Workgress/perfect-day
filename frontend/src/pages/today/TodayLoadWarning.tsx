import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { updateTask } from '@/shared/api/tasks'
import { apiError, apiProblem } from '@/shared/api/errors'
import { scheduleKeys, taskKeys } from '@/shared/api/planningKeys'
import type { DailySchedule } from '@/shared/model/schedule'
import { TASK_TYPES } from '@/shared/model/task'
import { Button } from '@/shared/ui/button/Button'
import { AlertTriangleIcon } from '@/shared/ui/icon/icons'
import { useSessionStore } from '@/stores/session'
import { formatDate } from '@/pages/biorhythms/biorhythmChartModel'
import { taskSessionRequest } from './taskSessionRequest'
import { useReplanLock } from './useScheduleReplan'
import { transferProposal } from './todayTransferModel'
import { timelineDuration } from './timelineModel'
import styles from './TodayDashboard.module.css'

export function TodayLoadWarning({ day, now }: { day: DailySchedule; now: number }) {
  const proposal = transferProposal(day, now)
  const [dismissed, setDismissed] = useState<string | null>(null)
  const generation = useSessionStore((state) => state.generation)
  const replanLocked = useReplanLock(generation)
  const sending = useRef(false)
  const client = useQueryClient()
  const navigate = useNavigate()
  const refresh = () =>
    Promise.allSettled([
      client.invalidateQueries({ queryKey: taskKeys.all(generation) }),
      client.invalidateQueries({ queryKey: scheduleKeys.all(generation) }),
    ])
  const mutation = useMutation({
    retry: false,
    mutationFn: async (selected: NonNullable<ReturnType<typeof transferProposal>>) =>
      taskSessionRequest(generation, (signal) =>
        updateTask(
          selected.task.id,
          { version: selected.task.version, planned_date: selected.date },
          signal,
        ),
      ),
    onSuccess: (task) => {
      if (useSessionStore.getState().generation !== generation) return
      client.setQueryData(taskKeys.detail(generation, task.id), task)
      navigate(paths.today, {
        replace: true,
        state: {
          taskNotice: {
            generation,
            message: `«${task.title}» (${TASK_TYPES[task.type]}, ${timelineDuration(task.duration_min)}) перенесена на ${formatDate(task.planned_date, { day: 'numeric', month: 'long' })}.`,
          },
        },
      })
      void refresh()
    },
    onError: (error) => {
      if (useSessionStore.getState().generation !== generation) return
      if (apiProblem(error)?.code === 'TASK_VERSION_CONFLICT') {
        navigate(paths.today, {
          replace: true,
          state: {
            taskNotice: {
              generation,
              message: 'Задача изменилась. Проверьте актуальный план перед переносом.',
            },
          },
        })
        void refresh()
      }
    },
    onSettled: () => {
      sending.current = false
    },
  })
  if (!proposal)
    return (
      <p className={styles.transferText} role="status">
        День перегружен. Подходящей задачи для переноса на завтра без нарушения дедлайна не найдено.
        Попробуйте изменить длительность или дату задач.
      </p>
    )
  if (dismissed === proposal.key)
    return (
      <p className={styles.transferText} role="status">
        Перенос отклонён. Сегодняшний план оставлен без изменений.
      </p>
    )
  const target = formatDate(proposal.date, { weekday: 'long', day: 'numeric', month: 'long' })
  return (
    <div className={styles.transfer}>
      <p className={styles.transferText}>
        Перенести «{proposal.task.title}» ({TASK_TYPES[proposal.task.type]},{' '}
        {timelineDuration(proposal.task.duration_min)}) на {target}?{' '}
        {proposal.released > 0
          ? `Так сегодня освободится ${timelineDuration(proposal.released)}.`
          : `Задача на сегодня, ${formatDate(day.date, { day: 'numeric', month: 'long' })}, но время для неё не назначено. Перенос ещё не выполнен.`}
      </p>
      <p className={styles.transferCaution}>
        <AlertTriangleIcon size={14} />
        <span>
          Свободное время на выбранный день ещё не подтверждено. После переноса задача может
          остаться без времени в расписании.
        </span>
      </p>
      {mutation.isError ? (
        <div className={styles.transferError} role="alert">
          <p>Не удалось подтвердить перенос. {apiError(mutation.error)}</p>
          <Button variant="ghost" size="s" onClick={() => void refresh()}>
            Обновить план
          </Button>
        </div>
      ) : null}
      <div className={styles.transferActions}>
        <Button
          variant="secondary"
          size="s"
          disabled={mutation.isPending || mutation.isError || replanLocked}
          onClick={() => {
            if (
              sending.current ||
              replanLocked ||
              client.isMutating({ mutationKey: ['schedule-replan', generation] })
            )
              return
            sending.current = true
            mutation.mutate(proposal)
          }}
        >
          {mutation.isPending
            ? 'Переносим…'
            : `Перенести на ${formatDate(proposal.date, { weekday: 'short', day: 'numeric' }).replace(',', '')}`}
        </Button>
        <Button
          variant="ghost"
          size="s"
          disabled={mutation.isPending}
          onClick={() => setDismissed(proposal.key)}
        >
          Оставить
        </Button>
      </div>
    </div>
  )
}
