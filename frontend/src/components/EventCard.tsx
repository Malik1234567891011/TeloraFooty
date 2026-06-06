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
      <div className="card-main">
        <span className="thumb-wrap">
          <img className="ethumb" src={api.thumbUrl(gameId, event.id)} alt={title} />
          <span className="tbadge">{fmtTime(event.timestamp)}</span>
        </span>
        <div className="card-body">
          <div className="card-top">
            <div className={`ttl ${event.type}`}>{title}</div>
            <button
              className="kebab"
              title="More"
              onClick={(e) => {
                e.stopPropagation()
                setMenuOpen(!menuOpen)
              }}
            >⋮</button>
          </div>
          <div className="chips">
            <span className={`chip${event.type === 'shot' ? ' chip-shot' : ''}`}>{event.source}</span>
            {event.verified && <span className="chip chip-ok">verified</span>}
          </div>
        </div>
      </div>

      <div className="card-strip" onClick={(e) => e.stopPropagation()}>
        <button
          className={`rate${event.verified ? ' confirmed' : ''}`}
          title="Correct call"
          onClick={onConfirm}
        >✓ Correct</button>
        <button className="rate bad" title="Bad call — remove" onClick={onRemove}>✗ Remove</button>
        <button title="Export clip" onClick={onExport}>⤓ Export</button>
      </div>

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
