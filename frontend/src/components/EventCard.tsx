import { useState } from 'react'
import { api } from '../api'
import { fmtTime } from '../playback'
import type { GameEvent } from '../types'

interface Props {
  gameId: string
  event: GameEvent
  selected: boolean
  onSelect: () => void
  onDelete: () => void
  onSwitchType: () => void
  onSetTimeToPlayhead: () => void
  onExport: () => void
  onConfirm: () => void
  onRemove: () => void
}

export default function EventCard({
  gameId, event, selected, onSelect, onDelete, onSwitchType, onSetTimeToPlayhead, onExport,
  onConfirm, onRemove,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false)
  const title = event.type === 'goal' ? 'Goal' : 'Shot on goal'

  return (
    <div className={`event-card${selected ? ' selected' : ''}`} onClick={onSelect}>
      <span style={{ position: 'relative' }}>
        <img className="ethumb" src={api.thumbUrl(gameId, event.id)} alt={title} />
        <span className="tbadge">{fmtTime(event.timestamp)}</span>
      </span>
      <span>
        <div className={`ttl ${event.type}`}>{title}</div>
        <div className="src">{event.source}{event.verified ? ' · verified' : ''}</div>
      </span>
      <span className="actions" onClick={(e) => e.stopPropagation()}>
        <button
          className={`rate${event.verified ? ' confirmed' : ''}`}
          title="Correct call"
          onClick={onConfirm}
        >✓</button>
        <button className="rate bad" title="Bad call — remove" onClick={onRemove}>✗</button>
        <button title="Export clip" onClick={onExport}>⤓</button>
        <button title="More" onClick={() => setMenuOpen(!menuOpen)}>⋮</button>
      </span>
      {menuOpen && (
        <div className="menu" onClick={(e) => e.stopPropagation()}>
          <button onClick={() => { setMenuOpen(false); onSwitchType() }}>
            Switch to {event.type === 'goal' ? 'shot' : 'goal'}
          </button>
          <button onClick={() => { setMenuOpen(false); onSetTimeToPlayhead() }}>
            Set time to playhead
          </button>
          <button onClick={() => { setMenuOpen(false); onDelete() }}>Delete</button>
        </div>
      )}
    </div>
  )
}
