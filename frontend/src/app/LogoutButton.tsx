import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { logoutSession } from './session'
import { apiError } from '@/shared/api/errors'
import { Button } from '@/shared/ui/button/Button'
import { FormMessage } from '@/shared/ui/form-field/FormField'

export function LogoutButton({ label = 'Выйти' }: { label?: string }) {
  const client = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const mutation = useMutation({
    mutationFn: logoutSession,
    retry: false,
    onSuccess: () => {
      void client.cancelQueries()
      client.removeQueries({ queryKey: ['session'] })
    },
  })
  return (
    <>
      <Button
        variant="ghost"
        size="s"
        disabled={mutation.isPending}
        onClick={() => {
          setError(null)
          mutation.mutate(undefined, { onError: (reason) => setError(apiError(reason)) })
        }}
      >
        {mutation.isPending ? 'Выходим…' : label}
      </Button>
      {error ? <FormMessage>{error}</FormMessage> : null}
    </>
  )
}
