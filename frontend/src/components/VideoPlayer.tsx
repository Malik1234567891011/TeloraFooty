import { useRef, useState } from 'react'
import { api } from '../api'
import { fmtTime, nextEvent, type Mode } from '../playback'
import type { GameEvent } from '../types'

interface Props {
  gameId: string
  duration: number
  events: GameEvent[]
  mode: Mode
  selected: GameEvent | null
  videoRef: React.RefObject<HTMLVideoElement | null>
  onTimeUpdate: (time: number) => void
  onSelectEvent: (event: GameEvent) => void
}

export default function VideoPlayer({
  gameId, duration, events, mode, selected, videoRef, onTimeUpdate, onSelectEvent,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)

  const video = () => videoRef.current

  function togglePlay() {
    const v = video()
    if (!v) return
    if (v.paused) v.play().catch(() => {})
    else v.pause()
  }

  function skip(delta: number) {
    const v = video()
    if (v) v.currentTime = Math.max(0, Math.min(duration, v.currentTime + delta))
  }

  function jumpEvent(dir: 1 | -1) {
    const ev = nextEvent(events, time, dir)
    if (ev) onSelectEvent(ev)
  }

  function onScrub(e: React.MouseEvent<HTMLDivElement>) {
    const v = video()
    if (!v || duration === 0) return
    const rect = e.currentTarget.getBoundingClientRect()
    const frac = (e.clientX - rect.left) / rect.width
    v.currentTime = Math.max(0, Math.min(duration, frac * duration))
  }

  function changeSpeed(value: number) {
    setSpeed(value)
    const v = video()
    if (v) v.playbackRate = value
  }

  const badge = selected
    ? `${mode === 'clip' ? 'CLIP' : 'FULL'} · ${selected.type.toUpperCase()} ${fmtTime(selected.timestamp)}`
    : mode === 'clip' ? 'CLIP MODE' : 'FULL GAME'

  return (
    <div className="video-col">
      <div className="video-wrap" ref={wrapRef}>
        <video
          ref={videoRef}
          src={api.videoUrl(gameId)}
          onClick={togglePlay}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onTimeUpdate={(e) => {
            const t = e.currentTarget.currentTime
            setTime(t)
            onTimeUpdate(t)
          }}
        />
        <div className="mode-badge">{badge}</div>
      </div>

      <div className="controls">
        <button onClick={togglePlay} title="Play/pause">{playing ? '❚❚' : '▶'}</button>
        <button onClick={() => jumpEvent(-1)} title="Previous event">⇤</button>
        <button onClick={() => jumpEvent(1)} title="Next event">⇥</button>
        <button onClick={() => skip(-5)} title="Back 5s">↺5</button>
        <button onClick={() => skip(5)} title="Forward 5s">5↻</button>

        <div className="timeline" onClick={onScrub}>
          <div className="track">
            <div className="fill" style={{ width: duration ? `${(time / duration) * 100}%` : '0%' }} />
            {events.map((ev) => (
              <span
                key={ev.id}
                className={`dot ${ev.type}${selected?.id === ev.id ? ' selected' : ''}`}
                style={{ left: duration ? `${(ev.timestamp / duration) * 100}%` : '0%' }}
                title={`${ev.type} ${fmtTime(ev.timestamp)}`}
                onClick={(e) => {
                  e.stopPropagation()
                  onSelectEvent(ev)
                }}
              />
            ))}
          </div>
        </div>

        <span className="time">{fmtTime(time)} / {fmtTime(duration)}</span>
        <select value={speed} onChange={(e) => changeSpeed(Number(e.target.value))} title="Speed">
          {[0.5, 1, 1.5, 2].map((s) => <option key={s} value={s}>{s}x</option>)}
        </select>
        <button onClick={() => wrapRef.current?.requestFullscreen()} title="Fullscreen">⛶</button>
      </div>
    </div>
  )
}
