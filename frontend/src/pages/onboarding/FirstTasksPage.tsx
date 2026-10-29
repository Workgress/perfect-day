import { useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { useSession } from '@/app/session/SessionContext'
import { Button } from '@/shared/ui/button/Button'
import { ArrowLeftIcon, CheckIcon } from '@/shared/ui/icon/icons'
import { OnboardingStep } from './OnboardingStep'

export function FirstTasksPage() {
  const navigate = useNavigate()
  const { completeOnboarding } = useSession().actions

  const handleFinish = () => {
    completeOnboarding()
    navigate(paths.today, { replace: true })
  }

  return (
    <OnboardingStep
      title="Первые задачи"
      description="Добавьте несколько дел — алгоритм сразу соберёт расписание на сегодня."
    >
      <Button variant="ghost" onClick={() => navigate(paths.onboarding.chronotype)}>
        <ArrowLeftIcon />
        Назад
      </Button>
      <Button onClick={handleFinish}>
        <CheckIcon />
        Готово
      </Button>
    </OnboardingStep>
  )
}
