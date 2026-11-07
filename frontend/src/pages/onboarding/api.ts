import { useMutation, useQueryClient } from '@tanstack/react-query'
import { getProfile, saveProfile, finishOnboarding, PROFILE_QUERY_KEY } from '@/shared/api/profile'
import { HttpError } from '@/shared/api/http'
import type { ProfileDocument, ProfilePatch } from '@/shared/model/profile'
import { useSessionStore } from '@/stores/session'

export function useSaveProfile() {
  const client = useQueryClient()
  const generation = useSessionStore((state) => state.generation)
  const apply = (document: ProfileDocument) => {
    if (
      useSessionStore.getState().generation !== generation ||
      !useSessionStore.getState().accessToken
    )
      throw new DOMException('Сессия изменилась', 'AbortError')
    useSessionStore.getState().applyProfile(document)
    client.setQueryData([...PROFILE_QUERY_KEY, generation], document)
  }
  const save = useMutation({
    mutationFn: async (patch: ProfilePatch) => {
      const document = await saveProfile(patch)
      apply(document)
      return document
    },
    retry: false,
  })
  const complete = useMutation({
    mutationFn: async ({
      body,
      key,
    }: {
      body: Parameters<typeof finishOnboarding>[0]
      key: string
    }) => {
      try {
        const document = await finishOnboarding(body, key)
        apply(document)
        return document
      } catch (error) {
        if (error instanceof HttpError && error.status === 409) {
          const document = await getProfile()
          apply(document)
          if (document.onboarding.completed_at) return document
        }
        throw error
      }
    },
    retry: false,
  })
  return { save, complete }
}
