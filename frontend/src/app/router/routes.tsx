import { Navigate, type RouteObject } from 'react-router'
import { AppLayout } from '@/app/layouts/AppLayout'
import { OnboardingLayout } from '@/app/layouts/OnboardingLayout'
import { RootLayout } from '@/app/layouts/RootLayout'
import { RouteErrorPage } from '@/pages/error/RouteErrorPage'
import { GuestOnly, OnboardingOnly, RequireAuth, RequireOnboarding } from './guards'
import { paths } from './paths'

const devRoutes: RouteObject[] = import.meta.env.DEV
  ? [
      {
        path: paths.kit,
        lazy: async () => ({ Component: (await import('@/pages/kit/KitPage')).KitPage }),
      },
    ]
  : []

export const routes: RouteObject[] = [
  {
    element: <RootLayout />,
    errorElement: <RouteErrorPage />,
    HydrateFallback: () => null,
    children: [
      {
        element: <GuestOnly />,
        children: [
          {
            path: paths.login,
            lazy: async () => ({ Component: (await import('@/pages/login/LoginPage')).LoginPage }),
          },
          {
            path: paths.register,
            lazy: async () => ({ Component: (await import('@/pages/login/LoginPage')).LoginPage }),
          },
        ],
      },
      {
        element: <RequireAuth />,
        children: [
          {
            path: paths.onboarding.root,
            element: <OnboardingOnly />,
            children: [
              {
                element: <OnboardingLayout />,
                children: [
                  { index: true, element: <Navigate to={paths.onboarding.birthDate} replace /> },
                  {
                    path: paths.onboarding.birthDate,
                    lazy: async () => ({
                      Component: (await import('@/pages/onboarding/BirthDatePage')).BirthDatePage,
                    }),
                  },
                  {
                    path: paths.onboarding.chronotype,
                    lazy: async () => ({
                      Component: (await import('@/pages/onboarding/ChronotypePage')).ChronotypePage,
                    }),
                  },
                  {
                    path: paths.onboarding.firstTasks,
                    lazy: async () => ({
                      Component: (await import('@/pages/onboarding/FirstTasksPage')).FirstTasksPage,
                    }),
                  },
                ],
              },
            ],
          },
          {
            element: <RequireOnboarding />,
            children: [
              {
                element: <AppLayout />,
                children: [
                  { path: '/', element: <Navigate to={paths.today} replace /> },
                  {
                    path: paths.today,
                    lazy: async () => ({
                      Component: (await import('@/pages/today/TodayPage')).TodayPage,
                    }),
                    children: [
                      {
                        path: paths.newTask,
                        lazy: async () => ({
                          Component: (await import('@/pages/today/NewTaskPage')).NewTaskPage,
                        }),
                      },
                    ],
                  },
                  {
                    path: paths.calendar,
                    lazy: async () => ({
                      Component: (await import('@/pages/calendar/CalendarPage')).CalendarPage,
                    }),
                  },
                  {
                    path: paths.biorhythms,
                    lazy: async () => ({
                      Component: (await import('@/pages/biorhythms/BiorhythmsPage')).BiorhythmsPage,
                    }),
                  },
                  {
                    path: paths.settings,
                    lazy: async () => ({
                      Component: (await import('@/pages/settings/SettingsPage')).SettingsPage,
                    }),
                  },
                ],
              },
            ],
          },
        ],
      },
      ...devRoutes,
      {
        path: '*',
        lazy: async () => ({
          Component: (await import('@/pages/not-found/NotFoundPage')).NotFoundPage,
        }),
      },
    ],
  },
]
