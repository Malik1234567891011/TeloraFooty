import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { clipWindow, fmtTime, nextEvent, type Mode } from '../playback'
import type { EventType, GameEvent } from '../types'

const SPEEDS = [0.5, 1, 1.5, 2, 4]

interface Props {
  gameId: string
  duration: number
  events: GameEvent[]
  mode: Mode
  selected: GameEvent | null
  videoRef: React.RefObject<HTMLVideoElement | null>
  onTimeUpdate: (time: number) => void
  onSelectEvent: (event: GameEvent) => void
  onTag: (type: EventType) => void
}

export default function VideoPlayer({
  gameId, duration, events, mode, selected, videoRef, onTimeUpdate, onSelectEvent, onTag,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const hideTimer = useRef<number | null>(null)
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [controlsVisible, setControlsVisible] = useState(true)
  const [burst, setBurst] = useState<{ icon: string; id: number } | null>(null)

  const video = () => videoRef.current

  // Netflix-style: controls fade away while playing, reappear on mouse activity.
  function pokeControls() {
    setControlsVisible(true)
    if (hideTimer.current) window.clearTimeout(hideTimer.current)
    hideTimer.current = window.setTimeout(() => {
      if (videoRef.current && !videoRef.current.paused) setControlsVisible(false)
    }, 2600)
  }

  useEffect(() => () => {
    if (hideTimer.current) window.clearTimeout(hideTimer.current)
  }, [])

  function togglePlay() {
    const v = video()
    if (!v) return
    if (v.paused) v.play().catch(() => {})
    else v.pause()
  }

  // In clip mode with a selection, the player presents only the clip's window:
  // the timeline spans clipStart→clipEnd, time reads 0:00/0:40, seeks stay inside.
  const win = clipWindow(mode, selected, duration)
  const winLen = win.end - win.start
  const relTime = Math.min(Math.max(time - win.start, 0), winLen)

  function skip(delta: number) {
    const v = video()
    if (v) v.currentTime = Math.max(win.start, Math.min(win.end, v.currentTime + delta))
  }

  function jumpEvent(dir: 1 | -1) {
    const ev = nextEvent(events, selected, time, dir)
    if (ev) onSelectEvent(ev)
  }

  function onScrub(e: React.MouseEvent<HTMLDivElement>) {
    const v = video()
    if (!v || winLen === 0) return
    const rect = e.currentTarget.getBoundingClientRect()
    const frac = (e.clientX - rect.left) / rect.width
    v.currentTime = Math.max(win.start, Math.min(win.end, win.start + frac * winLen))
  }

  function changeSpeed(value: number) {
    setSpeed(value)
    const v = video()
    if (v) v.playbackRate = value
  }

  function stepSpeed(dir: 1 | -1) {
    const idx = SPEEDS.indexOf(speed)
    const next = SPEEDS[Math.max(0, Math.min(SPEEDS.length - 1, idx + dir))]
    changeSpeed(next)
  }

  // Veo-style keyboard shortcuts: H = tag shot (Veo's clip key), G = tag goal,
  // +/- = speed, Space/K = play/pause, arrows = ±5s, N/P = next/prev event, F = fullscreen.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return
      switch (e.key.toLowerCase()) {
        case ' ':
        case 'k':
          e.preventDefault()
          togglePlay()
          break
        case 'arrowleft':
          e.preventDefault()
          skip(-5)
          break
        case 'arrowright':
          e.preventDefault()
          skip(5)
          break
        case '+':
        case '=':
          stepSpeed(1)
          break
        case '-':
          stepSpeed(-1)
          break
        case 'h':
          onTag('shot')
          break
        case 'g':
          onTag('goal')
          break
        case 'n':
          jumpEvent(1)
          break
        case 'p':
          jumpEvent(-1)
          break
        case 'f':
          wrapRef.current?.requestFullscreen()
          break
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const badge = selected
    ? `${mode === 'clip' ? 'CLIP' : 'FULL'} · ${selected.type.toUpperCase()} ${fmtTime(selected.timestamp)}`
    : mode === 'clip' ? 'CLIP MODE' : 'FULL GAME'

  return (
    <div className="video-col">
      <div
        className="video-wrap"
        ref={wrapRef}
        onMouseMove={pokeControls}
        onMouseLeave={() => {
          if (videoRef.current && !videoRef.current.paused) setControlsVisible(false)
        }}
      >
        <video
          ref={videoRef}
          src={api.videoUrl(gameId)}
          onClick={togglePlay}
          onPlay={() => {
            setPlaying(true)
            pokeControls()
            setBurst({ icon: '▶', id: Date.now() })
          }}
          onPause={() => {
            setPlaying(false)
            setControlsVisible(true)
            setBurst({ icon: '❚❚', id: Date.now() })
          }}
          onTimeUpdate={(e) => {
            const t = e.currentTarget.currentTime
            setTime(t)
            onTimeUpdate(t)
          }}
        />
        <div className="mode-badge">{badge}</div>

        {/* Netflix-style center burst on play/pause */}
        {burst && <div className="play-burst" key={burst.id}>{burst.icon}</div>}

        {/* Veo-style: controls live on the video under a gradient scrim */}
        <div className={`video-overlay${controlsVisible ? '' : ' hidden'}`}>
          <div className="timeline" onClick={onScrub}>
            <div className="track">
              <div className="fill" style={{ width: winLen ? `${(relTime / winLen) * 100}%` : '0%' }} />
              <span className="knob" style={{ left: winLen ? `${(relTime / winLen) * 100}%` : '0%' }} />
              {(mode === 'clip' && selected ? [selected] : events).map((ev) => (
                <span
                  key={ev.id}
                  className={`dot ${ev.type}${selected?.id === ev.id ? ' selected' : ''}`}
                  style={{ left: winLen ? `${((ev.timestamp - win.start) / winLen) * 100}%` : '0%' }}
                  title={`${ev.type} ${fmtTime(ev.timestamp)}`}
                  onClick={(e) => {
                    e.stopPropagation()
                    onSelectEvent(ev)
                  }}
                />
              ))}
            </div>
          </div>

          <div className="controls-row">
            <span className="time">{fmtTime(relTime)} / {fmtTime(winLen)}</span>
            <div className="transport">
              <button onClick={() => jumpEvent(-1)} title="Previous event (P)">⇤</button>
              <button onClick={() => skip(-5)} title="Back 5s (←)">↺5</button>
              <button className="play-btn" onClick={togglePlay} title="Play/pause (Space)">
                {playing ? '❚❚' : '▶'}
              </button>
              <button onClick={() => skip(5)} title="Forward 5s (→)">5↻</button>
              <button onClick={() => jumpEvent(1)} title="Next event (N)">⇥</button>
            </div>
            <div className="right">
              <select value={speed} onChange={(e) => changeSpeed(Number(e.target.value))} title="Speed (+/-)">
                {SPEEDS.map((s) => <option key={s} value={s}>{s}x</option>)}
              </select>
              <button onClick={() => wrapRef.current?.requestFullscreen()} title="Fullscreen (F)">⛶</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
