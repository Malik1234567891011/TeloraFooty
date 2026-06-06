import { useEffect, useRef, useState } from 'react'
import { fmtTime } from '../playback'

interface Props {
  src: string
}

/** Mini player for the export popup — same design language as the main VideoPlayer. */
export default function ClipPlayer({ src }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const hideTimer = useRef<number | null>(null)
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [controlsVisible, setControlsVisible] = useState(true)
  const [burst, setBurst] = useState<{ icon: string; id: number } | null>(null)

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
    const v = videoRef.current
    if (!v) return
    if (v.paused) v.play().catch(() => {})
    else v.pause()
  }

  function skip(delta: number) {
    const v = videoRef.current
    if (v) v.currentTime = Math.max(0, Math.min(duration, v.currentTime + delta))
  }

  function onScrub(e: React.MouseEvent<HTMLDivElement>) {
    const v = videoRef.current
    if (!v || duration === 0) return
    const rect = e.currentTarget.getBoundingClientRect()
    const frac = (e.clientX - rect.left) / rect.width
    v.currentTime = Math.max(0, Math.min(duration, frac * duration))
  }

  // Space / arrows control the preview while the popup is open.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return
      if (e.key === ' ' || e.key.toLowerCase() === 'k') {
        e.preventDefault()
        togglePlay()
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        skip(-5)
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        skip(5)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  return (
    <div
      className="video-wrap clip-player"
      ref={wrapRef}
      onMouseMove={pokeControls}
      onMouseLeave={() => {
        if (videoRef.current && !videoRef.current.paused) setControlsVisible(false)
      }}
    >
      <video
        ref={videoRef}
        src={src}
        autoPlay
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
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
      />

      {burst && <div className="play-burst" key={burst.id}>{burst.icon}</div>}

      <div className={`video-overlay${controlsVisible ? '' : ' hidden'}`}>
        <div className="timeline" onClick={onScrub}>
          <div className="track">
            <div className="fill" style={{ width: duration ? `${(time / duration) * 100}%` : '0%' }} />
            <span className="knob" style={{ left: duration ? `${(time / duration) * 100}%` : '0%' }} />
          </div>
        </div>
        <div className="controls-row">
          <span className="time">{fmtTime(time)} / {fmtTime(duration)}</span>
          <div className="transport">
            <button onClick={() => skip(-5)} title="Back 5s (←)">↺5</button>
            <button className="play-btn" onClick={togglePlay} title="Play/pause (Space)">
              {playing ? '❚❚' : '▶'}
            </button>
            <button onClick={() => skip(5)} title="Forward 5s (→)">5↻</button>
          </div>
          <div className="right">
            <button onClick={() => wrapRef.current?.requestFullscreen()} title="Fullscreen">⛶</button>
          </div>
        </div>
      </div>
    </div>
  )
}
