import { useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { TASK_TYPES, type OnboardingTask, type TaskType } from '@/shared/model/onboarding'
import { Button } from '@/shared/ui/button/Button'
import { FormMessage } from '@/shared/ui/form-field/FormField'
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  PlusIcon,
  SparklesIcon,
  XIcon,
} from '@/shared/ui/icon/icons'
import { useSessionStore } from '@/stores/session'
import { validateTasks } from './model'
import { OnboardingStep } from './OnboardingStep'
import styles from './OnboardingStep.module.css'

export function FirstTasksPage() {
  const navigate = useNavigate()
  const draft = useSessionStore((state) => state.onboarding)
  const update = useSessionStore((state) => state.updateOnboarding)
  const complete = useSessionStore((state) => state.completeOnboarding)
  const [error, setError] = useState<string | null>(null)
  const formRef = useRef<HTMLFormElement>(null)
  const updateTask = (id: string, patch: Partial<OnboardingTask>) => {
    update({ tasks: draft.tasks.map((task) => (task.id === id ? { ...task, ...patch } : task)) })
    setError(null)
  }
  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    const validation = validateTasks(draft)
    if (validation) {
      setError(validation)
      return
    }
    if (!import.meta.env.DEV) {
      setError('Построение плана пока недоступно. Введённые задачи сохранены.')
      return
    }
    setError(null)
    update({
      tasks: draft.tasks.map((task) => ({ ...task, title: task.title.trim() })),
      planReady: true,
    })
  }

  return (
    <OnboardingStep
      title="Что нужно сделать?"
      description="Добавьте задачи и выберите тип — система сама разложит их по времени и объяснит почему."
    >
      <form
        ref={formRef}
        className={styles.form}
        noValidate
        onSubmit={handleSubmit}
        aria-label="Первые задачи"
      >
        <div className={styles.taskList}>
          {!draft.tasks.length ? (
            <p className={`text-body ${styles.empty}`}>
              Пока нет задач. Добавьте первое дело на сегодня.
            </p>
          ) : null}
          {draft.tasks.map((task, index) => (
            <div key={task.id} className={styles.task} data-type={task.type}>
              <input
                className={styles.taskTitle}
                aria-label={`Название задачи ${index + 1}`}
                value={task.title}
                placeholder="Название задачи"
                maxLength={200}
                required
                onChange={(event) => updateTask(task.id, { title: event.target.value })}
              />
              <div className={styles.taskType}>
                <span aria-hidden="true" />
                <select
                  aria-label={`Тип задачи ${index + 1}`}
                  value={task.type}
                  onChange={(event) =>
                    updateTask(task.id, { type: event.target.value as TaskType })
                  }
                >
                  {Object.entries(TASK_TYPES).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              <label className={styles.duration}>
                <input
                  aria-label={`Длительность задачи ${index + 1}, минут`}
                  type="number"
                  min={5}
                  max={480}
                  step={5}
                  value={Number.isFinite(task.durationMin) ? task.durationMin : ''}
                  onChange={(event) =>
                    updateTask(task.id, { durationMin: event.target.valueAsNumber })
                  }
                />
                <span>мин</span>
              </label>
              <Button
                variant="ghost"
                size="s"
                aria-label={`Удалить задачу ${index + 1}`}
                onClick={() => {
                  update({ tasks: draft.tasks.filter((item) => item.id !== task.id) })
                  setError(null)
                }}
              >
                <XIcon size={16} />
              </Button>
            </div>
          ))}
          <Button
            className={styles.addTask}
            variant="ghost"
            onClick={() => {
              update({
                tasks: [
                  ...draft.tasks,
                  { id: crypto.randomUUID(), title: '', type: 'intellectual', durationMin: 60 },
                ],
              })
              setError(null)
              requestAnimationFrame(() => {
                const inputs =
                  formRef.current?.querySelectorAll<HTMLInputElement>('input[required]')
                inputs?.[inputs.length - 1]?.focus()
              })
            }}
          >
            <PlusIcon />
            Добавить задачу
          </Button>
        </div>
        {error ? <FormMessage>{error}</FormMessage> : null}
        {import.meta.env.DEV ? (
          <p className={`text-caption ${styles.secondary}`} role="status">
            Деморежим: задачи сохраняются в браузере. Пример плана не учитывает биоритмы и хронотип.
          </p>
        ) : null}
        <div className={styles.actions}>
          <Button variant="ghost" onClick={() => navigate(paths.onboarding.chronotype)}>
            <ArrowLeftIcon />
            Назад
          </Button>
          {draft.planReady && import.meta.env.DEV ? (
            <Button
              onClick={() => {
                complete()
                navigate(paths.today, { replace: true })
              }}
            >
              <ArrowRightIcon />
              Открыть план
            </Button>
          ) : (
            <Button type="submit">
              <SparklesIcon />
              Составить план
            </Button>
          )}
        </div>
      </form>
    </OnboardingStep>
  )
}
