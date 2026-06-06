import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import ExportModal from '../components/ExportModal'
import type { Game, GameEvent } from '../types'

const game: Game = {
  id: 'g1',
  title: 'Test Game',
  date: '2026-06-06',
  durationSec: 600,
  source: { kind: 'local', url: null },
  status: 'ready',
  error: null,
}

const event: GameEvent = {
  id: 'e1',
  type: 'goal',
  timestamp: 100,
  source: 'manual',
  verified: false,
  clipStart: 70,
  clipEnd: 110,
}

function setup() {
  const onClose = vi.fn()
  render(<ExportModal game={game} event={event} onClose={onClose} />)
  return { onClose }
}

test('shows the clip preview and a download link with the right filename', () => {
  setup()
  const video = document.querySelector('video.clip-preview')!
  expect(video).toBeInTheDocument()
  expect(video.getAttribute('src')).toBe('/api/games/g1/events/e1/clip.mp4')
  const link = screen.getByText('⤓ Download').closest('a')!
  expect(link.getAttribute('href')).toBe('/api/games/g1/events/e1/clip.mp4')
  expect(link.getAttribute('download')).toBe('Test_Game_goal_140.mp4')
})

test('send button stays disabled until a valid email is typed', () => {
  setup()
  const send = screen.getByRole('button', { name: 'Send email' })
  expect(send).toBeDisabled()
  fireEvent.change(screen.getByPlaceholderText('coach@example.com'), {
    target: { value: 'not-an-email' },
  })
  expect(send).toBeDisabled()
  fireEvent.change(screen.getByPlaceholderText('coach@example.com'), {
    target: { value: 'coach@example.com' },
  })
  expect(send).toBeEnabled()
})

test('sends the email and shows confirmation', async () => {
  const fetchMock = vi.spyOn(window, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ ok: true }), { status: 200 }),
  )
  setup()
  fireEvent.change(screen.getByPlaceholderText('coach@example.com'), {
    target: { value: 'coach@example.com' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Send email' }))
  expect(await screen.findByRole('button', { name: 'Sent ✓' })).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith(
    '/api/games/g1/events/e1/email',
    expect.objectContaining({ method: 'POST' }),
  )
  fetchMock.mockRestore()
})

test('surfaces email errors in the modal', async () => {
  const fetchMock = vi.spyOn(window, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ detail: "Email isn't configured" }), { status: 400 }),
  )
  setup()
  fireEvent.change(screen.getByPlaceholderText('coach@example.com'), {
    target: { value: 'coach@example.com' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Send email' }))
  expect(await screen.findByText("Email isn't configured")).toBeInTheDocument()
  fetchMock.mockRestore()
})
