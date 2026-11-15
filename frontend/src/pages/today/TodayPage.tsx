import { Outlet, useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { Button } from '@/shared/ui/button/Button'
import { PlusIcon } from '@/shared/ui/icon/icons'
import { PageHeader } from '@/shared/ui/page-header/PageHeader'

export function TodayPage() {
  const navigate = useNavigate()

  return (
    <>
      <title>Сегодня · Идеальный день</title>
      <PageHeader title="Сегодня" description="Энергетический профиль и план на день.">
        <Button data-new-task-trigger onClick={() => navigate(paths.newTask)}>
          <PlusIcon />
          Добавить задачу
        </Button>
      </PageHeader>
      <Outlet />
    </>
  )
}
