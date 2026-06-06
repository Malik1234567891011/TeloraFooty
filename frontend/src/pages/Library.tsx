import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { DriveFile, Game } from '../types'

export default function Library() {
  const [games, setGames] = useState<Game[]>([])
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [drivePick, setDrivePick] = useState<{ url: string; files: DriveFile[] } | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [driveImporting, setDriveImporting] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const refresh = () =>
    api.listGames()
      .then((gs) => {
        setGames(gs)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 2000) // poll while downloads/processing run
    return () => clearInterval(t)
  }, [])

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      await api.importFile(file)
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  async function onDrive() {
    const url = window.prompt('Paste a public Google Drive file or folder link:')
    if (!url) return
    setError(null)
    try {
      if (url.includes('/folders/')) {
        const files = await api.listDriveFolder(url)
        if (files.length === 0) {
          setError('No videos found in that folder')
          return
        }
        setChecked(new Set(files.map((f) => f.id)))
        setDrivePick({ url, files })
      } else {
        await api.importDrive(url)
        await refresh()
      }
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function confirmDrivePick() {
    if (!drivePick || driveImporting) return
    setDriveImporting(true)
    try {
      await api.importDrive(drivePick.url, [...checked])
      setDrivePick(null)
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setDriveImporting(false)
    }
  }

  async function onDelete(game: Game) {
    if (!window.confirm(`Delete "${game.title}"?`)) return
    try {
      await api.deleteGame(game.id)
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>TeloraFooty</h1>
          <div className="sub">Your match library</div>
        </div>
        <span className="spacer" />
        <button className="btn" onClick={() => fileInput.current?.click()} disabled={uploading}>
          {uploading ? 'Uploading…' : 'Import video'}
        </button>
        <button className="btn btn-primary" onClick={onDrive}>Import from Drive</button>
        <input ref={fileInput} type="file" accept=".mp4,.mov,.mkv" hidden onChange={onFile} />
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="library-grid">
        {games.map((g) => (
          <div key={g.id} className="game-card">
            {g.status === 'ready' ? (
              <Link to={`/games/${g.id}`}>
                <div className="thumb">
                  <video src={api.videoUrl(g.id)} preload="metadata" muted />
                </div>
              </Link>
            ) : (
              <div className="thumb">
                {g.status === 'error' ? (
                  <span className="status-error">⚠ {g.error ?? 'Import failed'}</span>
                ) : (
                  <span>{g.status === 'downloading' ? 'Downloading…' : 'Processing…'}</span>
                )}
              </div>
            )}
            <div className="info">
              <strong>{g.title}</strong>
              <div className="meta">
                {g.date} · {g.goals ?? 0} goals · {g.shots ?? 0} shots
              </div>
            </div>
            <button className="delete" onClick={() => onDelete(g)} title="Delete game">✕</button>
          </div>
        ))}
        {games.length === 0 && <p style={{ color: 'var(--muted)' }}>No games yet — import one to get started.</p>}
      </div>

      {drivePick && (
        <div className="modal-backdrop" onClick={() => setDrivePick(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Choose videos to import</h3>
            {drivePick.files.map((f) => (
              <label key={f.id}>
                <input
                  type="checkbox"
                  checked={checked.has(f.id)}
                  onChange={(e) => {
                    const next = new Set(checked)
                    if (e.target.checked) next.add(f.id)
                    else next.delete(f.id)
                    setChecked(next)
                  }}
                />{' '}
                {f.name}
              </label>
            ))}
            <div className="actions">
              <button className="btn" onClick={() => setDrivePick(null)}>Cancel</button>
              <button className="btn btn-primary" onClick={confirmDrivePick} disabled={driveImporting || checked.size === 0}>
                {driveImporting ? 'Importing…' : `Import ${checked.size} video${checked.size === 1 ? '' : 's'}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
