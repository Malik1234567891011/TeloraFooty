import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import ClipsPanel, { type ClipsPanelProps } from '../components/ClipsPanel'
import type { GameEvent } from '../types'

const ev = (id: string, type: 'shot' | 'goal', timestamp: number): GameEvent => ({
  id,
  type,
  timestamp,
  source: 'sample',
  verified: false,
  clipStart: Math.max(0, timestamp - 30),
  clipEnd: timestamp + 10,
})

const events = [ev('e1', 'shot', 100), ev('e2', 'goal', 200)]

function setup(overrides: Partial<ClipsPanelProps> = {}) {
  const props: ClipsPanelProps = {
    gameId: 'g1',
    events,
    tab: 'all',
    onTab: vi.fn(),
    mode: 'clip',
    onMode: vi.fn(),
    selected: null,
    onSelect: vi.fn(),
    onTag: vi.fn(),
    onDelete: vi.fn(),
    onSwitchType: vi.fn(),
    onSetTimeToPlayhead: vi.fn(),
    onExport: vi.fn(),
    onConfirm: vi.fn(),
    onRemove: vi.fn(),
    ...overrides,
  }
  render(<ClipsPanel {...props} />)
  return props
}

test('renders all events on the all tab', () => {
  setup()
  expect(screen.getByText('Shot on goal')).toBeInTheDocument()
  expect(screen.getByText('Goal')).toBeInTheDocument()
})

test('goals tab shows only goals', () => {
  setup({ tab: 'goals' })
  expect(screen.queryByText('Shot on goal')).not.toBeInTheDocument()
  expect(screen.getByText('Goal')).toBeInTheDocument()
})

test('shots tab shows only shots', () => {
  setup({ tab: 'shots' })
  expect(screen.getByText('Shot on goal')).toBeInTheDocument()
  expect(screen.queryByText('Goal')).not.toBeInTheDocument()
})

test('clicking a tab calls onTab', () => {
  const props = setup()
  fireEvent.click(screen.getByRole('button', { name: 'Goals' }))
  expect(props.onTab).toHaveBeenCalledWith('goals')
})

test('clicking the toggle calls onMode', () => {
  const props = setup()
  fireEvent.click(screen.getByRole('button', { name: 'Full game' }))
  expect(props.onMode).toHaveBeenCalledWith('full')
})

test('clicking a card calls onSelect with the event', () => {
  const props = setup()
  fireEvent.click(screen.getByText('Goal'))
  expect(props.onSelect).toHaveBeenCalledWith(events[1])
})

test('tag menu offers shot and goal and calls onTag', () => {
  const props = setup()
  fireEvent.click(screen.getByRole('button', { name: '+ Tag' }))
  fireEvent.click(screen.getByRole('button', { name: 'Tag goal' }))
  expect(props.onTag).toHaveBeenCalledWith('goal')
})

test('export button calls onExport with the event', () => {
  const props = setup()
  fireEvent.click(screen.getAllByTitle('Export clip')[0])
  expect(props.onExport).toHaveBeenCalledWith(events[0])
})

test('confirm button calls onConfirm with the event', () => {
  const props = setup()
  fireEvent.click(screen.getAllByTitle('Correct call')[0])
  expect(props.onConfirm).toHaveBeenCalledWith(events[0])
})

test('remove button calls onRemove with the event', () => {
  const props = setup()
  fireEvent.click(screen.getAllByTitle('Bad call — remove')[0])
  expect(props.onRemove).toHaveBeenCalledWith(events[0])
})

test('verified event shows the verified state', () => {
  setup({ events: [{ ...events[0], verified: true }] })
  expect(screen.getAllByTitle('Correct call')[0].className).toContain('confirmed')
})
