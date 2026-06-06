import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import VideoPlayer from '../components/VideoPlayer'
import { clipEnded, startTime, type FilterTab, type Mode } from '../playback'
import type { Game, GameEvent } from '../types'

export default function Player() {
  const { id } = useParams<{ id: string }>()
  const gameId = id!
  const [game, setGame] = useState<Game | null>(null)
  const [events, setEvents] = useState<GameEvent[]>([])
  const [mode, setMode] = useState<Mode>('clip')
  const [tab, setTab] = useState<FilterTab>('all')
  const [selected, setSelected] = useState<GameEvent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const lastTimeRef = useRef(0)

  const refreshEvents = useCallback(
    () => api.listEvents(gameId).then(setEvents).catch((e: Error) => setError(e.message)),
    [gameId],
  )

  useEffect(() => {
    api.getGame(gameId).then(setGame).catch((e: Error) => setError(e.message))
    refreshEvents()
  }, [gameId, refreshEvents])

  function selectEvent(ev: GameEvent) {
    setSelected(ev)
    const v = videoRef.current
    if (!v) return
    v.currentTime = startTime(mode, ev)
    v.play().catch(() => {})
  }

  function switchMode(m: Mode) {
    setMode(m)
    const v = videoRef.current
    if (m === 'clip' && selected && v) {
      v.currentTime = selected.clipStart
      v.play().catch(() => {})
    }
  }

  function onTimeUpdate(t: number) {
    const last = lastTimeRef.current
    lastTimeRef.current = t
    // Pause exactly once when playback crosses the clip's end.
    if (clipEnded(t, mode, selected) && !clipEnded(last, mode, selected)) {
      videoRef.current?.pause()
    }
  }

  // Task 10 removes these — needed for ClipsPanel wiring
  void tab; void setTab; void switchMode

  if (!game) return <div className="page">{error ?? 'Loading…'}</div>

  return (
    <div className="page">
      <div className="topbar">
        <Link to="/">← Library</Link>
        <span>
          <span className="title">{game.title}</span> <span className="sub">· {game.date}</span>
        </span>
        <span className="sub">{events.length} events</span>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="player-layout">
        <VideoPlayer
          gameId={gameId}
          duration={game.durationSec}
          events={events}
          mode={mode}
          selected={selected}
          videoRef={videoRef}
          onTimeUpdate={onTimeUpdate}
          onSelectEvent={selectEvent}
        />
        {/* ClipsPanel mounts here in Task 10 */}
        <div className="clips-panel" data-placeholder />
      </div>
    </div>
  )
}
