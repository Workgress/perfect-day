import { apiError, apiProblem } from '@/shared/api/errors'
import { getSchedule, getScheduleDetails, replanSchedule } from '@/shared/api/schedule'
import { getTask } from '@/shared/api/tasks'
import { plannerExplanation } from '@/shared/lib/plannerText'
import type { Task } from '@/shared/model/task'

export type CreatedTaskPlacement = { task: Task; explanation?: string }

/** A committed creation is never replayed when its subsequent placement fails. */
export async function placeCreatedTask(
  created: Task,
  timezone: string,
  signal: AbortSignal,
): Promise<CreatedTaskPlacement> {
  if (created.status !== 'pending' || created.is_pinned || created.is_date_locked)
    return { task: created }
  signal.throwIfAborted()
  let failure: unknown
  try {
    const source = await getSchedule(created.planned_date, signal).catch((error) => {
      if (apiProblem(error)?.code === 'SCHEDULE_NOT_FOUND') return null
      throw error
    })
    signal.throwIfAborted()
    if (source && source.timezone !== timezone)
      throw new Error('Часовой пояс расписания изменился. Обновите страницу.')
    await replanSchedule(created.planned_date, source?.version ?? 0, signal, true)
  } catch (error) {
    signal.throwIfAborted()
    failure = error
  }
  try {
    // Also reconcile a committed command whose response was lost, without another POST.
    const task = await getTask(created.id, signal)
    signal.throwIfAborted()
    if (task.id !== created.id) throw new Error('Сервер вернул другую задачу.')
    if (task.planned_date !== created.planned_date && task.status === 'scheduled')
      return {
        task,
        explanation: failure
          ? `Задача уже размещена на ${task.planned_date.split('-').reverse().join('.')}. Загружена её актуальная дата; повторно создавать задачу не нужно.`
          : `В выбранный день не нашлось подходящего окна на ${task.duration_min} мин. Планировщик перенёс задачу на ${task.planned_date.split('-').reverse().join('.')} с учётом свободного времени${task.deadline ? ' и срока' : ''}.`,
      }
    if (task.status !== 'pending') return { task }
    if (!failure) {
      const details = await getScheduleDetails(task.planned_date, signal).catch(() => null)
      signal.throwIfAborted()
      const reason = details?.unscheduled_explanations.find((item) => item.task_id === task.id)
      if (details?.schedule.timezone === timezone && reason)
        return { task, explanation: plannerExplanation(reason.explanation) }
    }
    return {
      task,
      explanation: failure
        ? `Задача создана, но автоматическое размещение не подтверждено. ${apiError(failure)} Откройте задачу и проверьте план перед повторным действием.`
        : 'Планировщик проверил перенос на другие дни, но подходящего окна с учётом срока и ограничений не нашлось. Задача сохранена без времени. Измените срок или длительность.',
    }
  } catch {
    signal.throwIfAborted()
    return {
      task: created,
      explanation:
        'Задача создана, но не удалось загрузить результат размещения. Откройте задачу и проверьте её дату и время. Создавать её повторно не нужно.',
    }
  }
}
