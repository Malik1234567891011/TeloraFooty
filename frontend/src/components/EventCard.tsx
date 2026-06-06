import { useState } from 'react'
import { api } from '../api'
import { fmtTime } from '../playback'
import type { GameEvent } from '../types'

interface Props {
  gameId: string
  event: GameEvent
  index?: number
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
  gameId, event, index = 0, selected, onSelect, onDelete, onSwitchType, onSetTimeToPlayhead, onExport,
  onConfirm, onRemove,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const [flashGood, setFlashGood] = useState(false)
  const title = event.type === 'goal' ? 'Goal' : 'Shot on goal'

  const LEAVE_MS = 600 // keep in sync with the card-out animation in index.css

  function confirm() {
    if (!event.verified) {
      setFlashGood(true)
      window.setTimeout(() => setFlashGood(false), 700)
    }
    onConfirm()
  }

  function remove() {
    // Play the red slide-out first, then actually delete.
    setLeaving(true)
    window.setTimeout(onRemove, LEAVE_MS)
  }

  return (
    <div
      className={`event-card${selected ? ' selected' : ''}${leaving ? ' leaving' : ''}${flashGood ? ' flash-good' : ''}`}
      style={{ animationDelay: leaving ? '0ms' : `${Math.min(index, 8) * 40}ms` }}
      onClick={onSelect}
    >
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
          </div>
        </div>
      </div>

      <div className="card-strip" onClick={(e) => e.stopPropagation()}>
        {event.verified ? (
          <span className="strip-verified">✓ Verified</span>
        ) : (
          <>
            <button className="rate" title="Correct call" onClick={confirm}>✓ Correct</button>
            <button className="rate bad" title="Bad call — remove" onClick={remove}>✗ Remove</button>
          </>
        )}
        <button title="Export clip" onClick={onExport}>⤓ Export</button>
      </div>

      {menuOpen && (
        <div className="menu" onClick={(e) => e.stopPropagation()}>
          {event.verified && (
            <button onClick={() => { setMenuOpen(false); onConfirm() }}>Unverify</button>
          )}
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
