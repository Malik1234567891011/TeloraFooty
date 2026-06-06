import type { EventType, GameEvent } from './types'

export type Mode = 'clip' | 'full'
export type FilterTab = 'all' | 'goals' | 'shots'

export function filterEvents(events: GameEvent[], tab: FilterTab): GameEvent[] {
  if (tab === 'all') return events
  const type: EventType = tab === 'goals' ? 'goal' : 'shot'
  return events.filter((e) => e.type === type)
}

export function sortEvents(events: GameEvent[]): GameEvent[] {
  return [...events].sort((a, b) => a.timestamp - b.timestamp)
}

/** True when clip-mode playback has reached the end of the selected event's window. */
export function clipEnded(time: number, mode: Mode, selected: GameEvent | null): boolean {
  return mode === 'clip' && selected !== null && time >= selected.clipEnd
}

/** Where to seek when an event is selected. */
export function startTime(mode: Mode, event: GameEvent): number {
  return mode === 'clip' ? event.clipStart : event.timestamp
}

/**
 * Next (dir=1) or previous (dir=-1) event.
 *
 * With a selected event, navigation follows event order — the playhead can sit
 * 30s before the selected timestamp in clip mode, so playhead-relative search
 * would keep re-finding the same event. Without a selection it falls back to
 * the playhead position.
 */
export function nextEvent(
  events: GameEvent[],
  selected: GameEvent | null,
  currentTime: number,
  dir: 1 | -1,
): GameEvent | null {
  const sorted = sortEvents(events)
  if (selected) {
    const idx = sorted.findIndex((e) => e.id === selected.id)
    if (idx !== -1) return sorted[idx + dir] ?? null
  }
  if (dir === 1) return sorted.find((e) => e.timestamp > currentTime + 0.5) ?? null
  return [...sorted].reverse().find((e) => e.timestamp < currentTime - 0.5) ?? null
}

export function fmtTime(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}
