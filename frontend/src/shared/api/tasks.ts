import type { TaskCreateRequest, TaskListQuery, TaskUpdateRequest } from '@/shared/model/task'
import { http } from './http'
import { readTask, readTaskList } from './planningValidation'

const WRITABLE_FIELDS = [
  'title',
  'description',
  'type',
  'priority',
  'duration_min',
  'planned_date',
  'deadline',
]

function writeBody(body: TaskCreateRequest | TaskUpdateRequest, update = false) {
  const allowed = update ? [...WRITABLE_FIELDS, 'version'] : WRITABLE_FIELDS
  if (Object.keys(body).some((field) => !allowed.includes(field)))
    throw new TypeError('Запрос содержит поля, которые API задач не поддерживает.')
  if (
    update &&
    !WRITABLE_FIELDS.some(
      (field) => Object.hasOwn(body, field) && body[field as keyof typeof body] !== undefined,
    )
  )
    throw new TypeError('Передайте хотя бы одно изменённое поле задачи.')
  return body
}

export async function getTask(id: string, signal?: AbortSignal) {
  return readTask(
    await http<unknown>(`/tasks/${encodeURIComponent(id)}`, { signal, cache: 'no-store' }),
  )
}

export async function getTasks(query: TaskListQuery = {}, signal?: AbortSignal) {
  return readTaskList(
    await http<unknown>('/tasks', { query: { ...query }, signal, cache: 'no-store' }),
  )
}

export async function createTask(body: TaskCreateRequest, signal?: AbortSignal) {
  return readTask(await http<unknown>('/tasks', { method: 'POST', body: writeBody(body), signal }))
}

export async function updateTask(id: string, body: TaskUpdateRequest, signal?: AbortSignal) {
  return readTask(
    await http<unknown>(`/tasks/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: writeBody(body, true),
      signal,
    }),
  )
}

export async function deleteTask(id: string, version: number, signal?: AbortSignal): Promise<void> {
  await http<void>(`/tasks/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    query: { version },
    signal,
  })
}

async function changeStatus(
  id: string,
  version: number,
  command: 'complete' | 'skip' | 'reopen',
  signal?: AbortSignal,
) {
  return readTask(
    await http<unknown>(`/tasks/${encodeURIComponent(id)}/${command}`, {
      method: 'POST',
      body: { version },
      signal,
    }),
  )
}

export const completeTask = (id: string, version: number, signal?: AbortSignal) =>
  changeStatus(id, version, 'complete', signal)
export const skipTask = (id: string, version: number, signal?: AbortSignal) =>
  changeStatus(id, version, 'skip', signal)
export const reopenTask = (id: string, version: number, signal?: AbortSignal) =>
  changeStatus(id, version, 'reopen', signal)
