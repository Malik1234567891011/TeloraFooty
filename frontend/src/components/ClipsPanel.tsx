import { useState } from 'react'
import { filterEvents, sortEvents, type FilterTab, type Mode } from '../playback'
import type { EventType, GameEvent } from '../types'
import EventCard from './EventCard'

export interface ClipsPanelProps {
  gameId: string
  events: GameEvent[]
  tab: FilterTab
  onTab: (tab: FilterTab) => void
  mode: Mode
  onMode: (mode: Mode) => void
  selected: GameEvent | null
  onSelect: (event: GameEvent) => void
  onTag: (type: EventType) => void
  onDelete: (event: GameEvent) => void
  onSwitchType: (event: GameEvent) => void
  onSetTimeToPlayhead: (event: GameEvent) => void
  onExport: (event: GameEvent) => void
  onConfirm: (event: GameEvent) => void
  onRemove: (event: GameEvent) => void
}

const TABS: { key: FilterTab; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'goals', label: 'Goals' },
  { key: 'shots', label: 'Shots' },
]

export default function ClipsPanel({
  gameId, events, tab, onTab, mode, onMode, selected,
  onSelect, onTag, onDelete, onSwitchType, onSetTimeToPlayhead, onExport,
  onConfirm, onRemove,
}: ClipsPanelProps) {
  const [tagOpen, setTagOpen] = useState(false)
  const visible = sortEvents(filterEvents(events, tab))

  return (
    <div className="clips-panel">
      <div className="head">
        <h3>Clips</h3>
        <div className="toggle">
          <button className={mode === 'clip' ? 'active' : ''} onClick={() => onMode('clip')}>
            Clip
          </button>
          <button className={mode === 'full' ? 'active' : ''} onClick={() => onMode('full')}>
            Full game
          </button>
        </div>
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`tab${tab === t.key ? ' active' : ''}`}
            onClick={() => onTab(t.key)}
          >
            {t.label}
          </button>
        ))}
        <span className="tag-btn tag-menu">
          <button className="tab" onClick={() => setTagOpen(!tagOpen)}>+ Tag</button>
          {tagOpen && (
            <div className="menu">
              <button onClick={() => { setTagOpen(false); onTag('shot') }}>Tag shot</button>
              <button onClick={() => { setTagOpen(false); onTag('goal') }}>Tag goal</button>
            </div>
          )}
        </span>
      </div>

      {visible.map((ev) => (
        <EventCard
          key={ev.id}
          gameId={gameId}
          event={ev}
          selected={selected?.id === ev.id}
          onSelect={() => onSelect(ev)}
          onDelete={() => onDelete(ev)}
          onSwitchType={() => onSwitchType(ev)}
          onSetTimeToPlayhead={() => onSetTimeToPlayhead(ev)}
          onExport={() => onExport(ev)}
          onConfirm={() => onConfirm(ev)}
          onRemove={() => onRemove(ev)}
        />
      ))}
      {visible.length === 0 && (
        <p className="empty-note">No events — use + Tag while watching to add one.</p>
      )}
    </div>
  )
}
