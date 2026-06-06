import { useEffect, useState } from 'react'
import { api } from '../api'
import { fmtTime } from '../playback'
import type { Game, GameEvent } from '../types'
import ClipPlayer from './ClipPlayer'

interface Props {
  game: Game
  event: GameEvent
  onClose: () => void
}

export default function ExportModal({ game, event, onClose }: Props) {
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')
  const title = event.type === 'goal' ? 'Goal' : 'Shot'
  const clipUrl = api.clipUrl(game.id, event.id)
  const filename = `${game.title.replaceAll(' ', '_')}_${event.type}_${fmtTime(event.timestamp).replace(':', '')}.mp4`
  const validEmail = /\S+@\S+\.\S+/.test(email)

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function send() {
    if (!validEmail || status === 'sending') return
    setStatus('sending')
    setErrorMsg('')
    try {
      await api.emailClip(game.id, event.id, email.trim())
      setStatus('sent')
    } catch (e) {
      setErrorMsg((e as Error).message)
      setStatus('error')
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal export-modal" onClick={(e) => e.stopPropagation()}>
        <h3>{title} · {fmtTime(event.timestamp)}</h3>
        <p className="modal-hint">{game.title} — 30s before → 10s after</p>

        <ClipPlayer src={clipUrl} />

        <div className="export-row">
          <a className="btn btn-primary" href={clipUrl} download={filename}>⤓ Download</a>
          <div className="email-row">
            <input
              className="modal-input"
              type="email"
              placeholder="coach@example.com"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value)
                if (status === 'sent' || status === 'error') setStatus('idle')
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') send()
              }}
            />
            <button
              className={`btn${status === 'sent' ? ' btn-primary' : ''}`}
              onClick={send}
              disabled={!validEmail || status === 'sending'}
            >
              {status === 'sending' ? 'Sending…' : status === 'sent' ? 'Sent ✓' : 'Send email'}
            </button>
          </div>
        </div>
        {status === 'error' && <p className="modal-error">{errorMsg}</p>}

        <div className="actions">
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  )
}
