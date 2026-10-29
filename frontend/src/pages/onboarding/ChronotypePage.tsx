import { useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { Button } from '@/shared/ui/button/Button'
import { ArrowLeftIcon, ArrowRightIcon } from '@/shared/ui/icon/icons'
import { OnboardingStep } from './OnboardingStep'

export function ChronotypePage() {
  const navigate = useNavigate()

  return (
    <OnboardingStep
      title="Хронотип и режим"
      description="Жаворонок, сова или голубь — от этого зависят пиковые часы для сложных задач."
    >
      <Button variant="ghost" onClick={() => navigate(paths.onboarding.birthDate)}>
        <ArrowLeftIcon />
        Назад
      </Button>
      <Button onClick={() => navigate(paths.onboarding.firstTasks)}>
        Далее
        <ArrowRightIcon />
      </Button>
    </OnboardingStep>
  )
}
