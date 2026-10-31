import { useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { Button } from '@/shared/ui/button/Button'
import { ArrowRightIcon } from '@/shared/ui/icon/icons'
import { OnboardingStep } from './OnboardingStep'

export function BirthDatePage() {
  const navigate = useNavigate()

  return (
    <OnboardingStep
      title="Дата рождения"
      description="От даты и времени рождения считаются физический, эмоциональный и интеллектуальный циклы."
    >
      <Button onClick={() => navigate(paths.onboarding.chronotype)}>
        Далее
        <ArrowRightIcon />
      </Button>
    </OnboardingStep>
  )
}
