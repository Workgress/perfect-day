import type { TaskListQuery } from '@/shared/model/task'

export const taskKeys = {
  all: (generation: number) => ['tasks', generation] as const,
  lists: (generation: number) => [...taskKeys.all(generation), 'list'] as const,
  list: (generation: number, query: TaskListQuery) =>
    [...taskKeys.lists(generation), query] as const,
  day: (generation: number, date: string) => [...taskKeys.lists(generation), 'day', date] as const,
  detail: (generation: number, id: string) => [...taskKeys.all(generation), 'detail', id] as const,
}

export const scheduleKeys = {
  all: (generation: number) => ['schedule', generation] as const,
  day: (generation: number, date: string) => [...scheduleKeys.all(generation), date] as const,
  details: (generation: number, date: string, version: number) =>
    [...scheduleKeys.day(generation, date), 'details', version] as const,
}
