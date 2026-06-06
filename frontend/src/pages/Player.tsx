import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import ClipsPanel from '../components/ClipsPanel'
import VideoPlayer from '../components/VideoPlayer'
import { clipEnded, fmtTime, startTime, type FilterTab, type Mode } from '../playback'
import type { EventType, Game, GameEvent } from '../types'

export default function Player() {
  const { id } = useParams<{ id: string }>()
  const gameId = id!
  const [game, setGame] = useState<Game | null>(null)
  const [events, setEvents] = useState<GameEvent[]>([])
  const [mode, setMode] = useState<Mode>('full')
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

  async function tagEvent(type: EventType) {
    const t = videoRef.current?.currentTime ?? 0
    try {
      const ev = await api.createEvent(gameId, type, t)
      await refreshEvents()
      setSelected(ev)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function deleteEvent(ev: GameEvent) {
    if (!window.confirm(`Delete this ${ev.type}?`)) return
    try {
      await api.deleteEvent(gameId, ev.id)
      if (selected?.id === ev.id) setSelected(null)
      await refreshEvents()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function switchType(ev: GameEvent) {
    try {
      const updated = await api.patchEvent(gameId, ev.id, { type: ev.type === 'goal' ? 'shot' : 'goal' })
      if (selected?.id === ev.id) setSelected(updated)
      await refreshEvents()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function setTimeToPlayhead(ev: GameEvent) {
    const t = videoRef.current?.currentTime ?? ev.timestamp
    try {
      const updated = await api.patchEvent(gameId, ev.id, { timestamp: t })
      if (selected?.id === ev.id) setSelected(updated)
      await refreshEvents()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function confirmEvent(ev: GameEvent) {
    try {
      const updated = await api.patchEvent(gameId, ev.id, { verified: !ev.verified })
      if (selected?.id === ev.id) setSelected(updated)
      await refreshEvents()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function removeEvent(ev: GameEvent) {
    // Bad call — one click, no confirm dialog.
    try {
      await api.deleteEvent(gameId, ev.id)
      if (selected?.id === ev.id) setSelected(null)
      await refreshEvents()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function exportEvent(ev: GameEvent) {
    try {
      const blob = await api.exportClip(gameId, ev.id)
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `${game!.title.replaceAll(' ', '_')}_${ev.type}_${fmtTime(ev.timestamp).replace(':', '')}.mp4`
      a.click()
      setTimeout(() => URL.revokeObjectURL(a.href), 1000)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (!game) return <div className="page">{error ?? 'Loading…'}</div>

  return (
    <div className="page">
      <div className="page-head">
        <Link to="/" className="back-btn" title="Back to library">←</Link>
        <div>
          <h1>{game.title}</h1>
          <div className="sub">{game.date} · {events.length} events</div>
        </div>
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
          onTag={tagEvent}
        />
        <ClipsPanel
          gameId={gameId}
          events={events}
          tab={tab}
          onTab={setTab}
          mode={mode}
          onMode={switchMode}
          selected={selected}
          onSelect={selectEvent}
          onTag={tagEvent}
          onDelete={deleteEvent}
          onSwitchType={switchType}
          onSetTimeToPlayhead={setTimeToPlayhead}
          onExport={exportEvent}
          onConfirm={confirmEvent}
          onRemove={removeEvent}
        />
      </div>

      <p className="kbd-hints">
        Space play/pause · ←/→ ±5s · <strong>H</strong> tag shot · <strong>G</strong> tag goal ·
        N/P next/prev event · +/− speed · F fullscreen
      </p>
    </div>
  )
}
