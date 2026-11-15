import { StrictMode } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, Outlet, RouterProvider, useNavigate } from 'react-router'
import { NewTaskPage } from './NewTaskPage'

function Today() {
  const navigate = useNavigate()
  return (
    <>
      <button data-new-task-trigger onClick={() => navigate('/today/new')}>
        Добавить задачу
      </button>
      <Outlet />
    </>
  )
}

describe('new task dialog', () => {
  it('opens without premature errors in StrictMode and restores focus and scrolling on Escape', async () => {
    const router = createMemoryRouter(
      [
        {
          path: '/today',
          element: <Today />,
          children: [{ path: 'new', element: <NewTaskPage /> }],
        },
      ],
      { initialEntries: ['/today'] },
    )
    render(
      <StrictMode>
        <RouterProvider router={router} />
      </StrictMode>,
    )
    const trigger = screen.getByRole('button', { name: 'Добавить задачу' })
    await userEvent.click(trigger)
    expect(await screen.findByRole('dialog', { name: 'Новая задача' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Название' })).toHaveFocus()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(document.body.style.overflow).toBe('hidden')
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
    expect(document.body.style.overflow).toBe('')
  })
})
