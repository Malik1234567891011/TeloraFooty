import { describe, expect, test } from 'vitest'
import { clipEnded, clipWindow, filterEvents, fmtTime, nextEvent, sortEvents, startTime } from '../playback'
import type { GameEvent } from '../types'

const ev = (id: string, type: 'shot' | 'goal', timestamp: number): GameEvent => ({
  id,
  type,
  timestamp,
  source: 'manual',
  verified: false,
  clipStart: Math.max(0, timestamp - 30),
  clipEnd: timestamp + 10,
})

const events = [ev('e2', 'goal', 200), ev('e1', 'shot', 100), ev('e3', 'shot', 300)]

describe('filterEvents', () => {
  test('all returns everything', () => expect(filterEvents(events, 'all')).toHaveLength(3))
  test('goals filters to goal type', () =>
    expect(filterEvents(events, 'goals').map((e) => e.id)).toEqual(['e2']))
  test('shots filters to shot type', () =>
    expect(filterEvents(events, 'shots').map((e) => e.id)).toEqual(['e1', 'e3']))
})

test('sortEvents orders by timestamp without mutating', () => {
  expect(sortEvents(events).map((e) => e.id)).toEqual(['e1', 'e2', 'e3'])
  expect(events[0].id).toBe('e2')
})

describe('clipEnded', () => {
  const e = ev('x', 'goal', 100) // clip 70 → 110
  test('true at/after clipEnd in clip mode', () => {
    expect(clipEnded(110, 'clip', e)).toBe(true)
    expect(clipEnded(115, 'clip', e)).toBe(true)
  })
  test('false before clipEnd', () => expect(clipEnded(109.5, 'clip', e)).toBe(false))
  test('false in full mode or with no selection', () => {
    expect(clipEnded(115, 'full', e)).toBe(false)
    expect(clipEnded(115, 'clip', null)).toBe(false)
  })
})

test('startTime: clipStart in clip mode, timestamp in full mode', () => {
  const e = ev('x', 'shot', 100)
  expect(startTime('clip', e)).toBe(70)
  expect(startTime('full', e)).toBe(100)
})

describe('nextEvent without a selection (playhead-based)', () => {
  test('finds next after current time', () => expect(nextEvent(events, null, 150, 1)?.id).toBe('e2'))
  test('finds previous before current time', () => expect(nextEvent(events, null, 150, -1)?.id).toBe('e1'))
  test('null at the edges', () => {
    expect(nextEvent(events, null, 300, 1)).toBeNull()
    expect(nextEvent(events, null, 100, -1)).toBeNull()
  })
})

describe('nextEvent with a selection (event-order based)', () => {
  const selected = events.find((e) => e.id === 'e2')!
  test('next returns the following event even when playhead is before the selected timestamp (clip mode)', () => {
    // In clip mode the playhead sits 30s BEFORE the selected event's timestamp —
    // navigation must follow event order, not the playhead.
    expect(nextEvent(events, selected, selected.clipStart, 1)?.id).toBe('e3')
  })
  test('prev returns the preceding event', () => {
    expect(nextEvent(events, selected, selected.clipStart, -1)?.id).toBe('e1')
  })
  test('null at the edges', () => {
    const last = events.find((e) => e.id === 'e3')!
    const first = events.find((e) => e.id === 'e1')!
    expect(nextEvent(events, last, 270, 1)).toBeNull()
    expect(nextEvent(events, first, 70, -1)).toBeNull()
  })
})

describe('clipWindow', () => {
  const e = ev('x', 'goal', 1200) // clip 1170 → 1210
  test('clip mode with a selection scopes the player to the clip', () => {
    expect(clipWindow('clip', e, 7200)).toEqual({ start: 1170, end: 1210 })
  })
  test('full mode spans the whole video', () => {
    expect(clipWindow('full', e, 7200)).toEqual({ start: 0, end: 7200 })
  })
  test('clip mode without a selection spans the whole video', () => {
    expect(clipWindow('clip', null, 7200)).toEqual({ start: 0, end: 7200 })
  })
})

test('fmtTime formats m:ss', () => {
  expect(fmtTime(0)).toBe('0:00')
  expect(fmtTime(65)).toBe('1:05')
  expect(fmtTime(3380)).toBe('56:20')
})
