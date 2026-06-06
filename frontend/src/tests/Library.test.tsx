import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import Library from '../pages/Library'
import { api } from '../api'
import type { Game } from '../types'

const game = (over: Partial<Game> = {}): Game => ({
  id: 'g1', title: 'Match', date: '2026-06-06', durationSec: 100,
  source: { kind: 'local', url: null }, status: 'processing', error: null,
  goals: 0, shots: 0, ...over,
})

beforeEach(() => vi.restoreAllMocks())
afterEach(() => vi.restoreAllMocks())

test('shows a progress bar with message while processing', async () => {
  vi.spyOn(api, 'listGames').mockResolvedValue([
    game({ status: 'processing', progress: 37, progressMessage: 'Scanning 3/8 windows' }),
  ])
  render(<MemoryRouter><Library /></MemoryRouter>)
  await waitFor(() => expect(screen.getByText('Scanning 3/8 windows')).toBeInTheDocument())
  expect(screen.getByTestId('progress-fill').style.width).toBe('37%')
})

test('interrupted game shows Retry which calls retryAnalysis', async () => {
  vi.spyOn(api, 'listGames').mockResolvedValue([
    game({ status: 'interrupted', error: 'Analysis was interrupted (server restart). Retry to resume.' }),
  ])
  const retry = vi.spyOn(api, 'retryAnalysis').mockResolvedValue({ job_id: 'j1' })
  render(<MemoryRouter><Library /></MemoryRouter>)
  const btn = await screen.findByRole('button', { name: /retry/i })
  fireEvent.click(btn)
  await waitFor(() => expect(retry).toHaveBeenCalledWith('g1'))
})
