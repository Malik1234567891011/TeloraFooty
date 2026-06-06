import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import ProgressBar from '../components/ProgressBar'
import type { DriveFile, Game } from '../types'

type DriveStep =
  | { step: 'url' }
  | { step: 'loading' }
  | { step: 'pick'; url: string; files: DriveFile[] }

export default function Library() {
  const [games, setGames] = useState<Game[]>([])
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [drive, setDrive] = useState<DriveStep | null>(null)
  const [driveUrl, setDriveUrl] = useState('')
  const [driveError, setDriveError] = useState<string | null>(null)
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

  function openDrive() {
    setDriveUrl('')
    setDriveError(null)
    setDrive({ step: 'url' })
  }

  function closeDrive() {
    setDrive(null)
    setDriveError(null)
  }

  async function submitDriveUrl() {
    const url = driveUrl.trim()
    if (!url || drive?.step === 'loading') return
    setDriveError(null)
    try {
      if (url.includes('/folders/')) {
        setDrive({ step: 'loading' })
        const files = await api.listDriveFolder(url)
        if (files.length === 0) {
          setDriveError('No videos found in that folder.')
          setDrive({ step: 'url' })
          return
        }
        setChecked(new Set(files.map((f) => f.id)))
        setDrive({ step: 'pick', url, files })
      } else {
        setDrive({ step: 'loading' })
        await api.importDrive(url)
        closeDrive()
        await refresh()
      }
    } catch (err) {
      setDriveError((err as Error).message)
      setDrive({ step: 'url' })
    }
  }

  async function confirmDrivePick() {
    if (drive?.step !== 'pick' || driveImporting) return
    setDriveImporting(true)
    try {
      await api.importDrive(drive.url, [...checked])
      closeDrive()
      await refresh()
    } catch (err) {
      setDriveError((err as Error).message)
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

  async function onRetry(game: Game) {
    try {
      await api.retryAnalysis(game.id)
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
        <button className="btn btn-primary" onClick={openDrive}>Import from Drive</button>
        <input ref={fileInput} type="file" accept=".mp4,.mov,.mkv" hidden onChange={onFile} />
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="library-grid">
        {games.map((g, i) => (
          <div key={g.id} className="game-card" style={{ animationDelay: `${Math.min(i, 8) * 50}ms` }}>
            {g.status === 'ready' ? (
              <Link to={`/games/${g.id}`}>
                <div className="thumb">
                  <video src={api.videoUrl(g.id)} preload="metadata" muted />
                </div>
              </Link>
            ) : (
              <div className="thumb">
                {g.status === 'error' || g.status === 'interrupted' ? (
                  <div className="thumb-state">
                    <span className="status-error">⚠ {g.error ?? 'Analysis failed'}</span>
                    <button className="btn btn-small" onClick={() => onRetry(g)}>Retry</button>
                  </div>
                ) : (
                  <ProgressBar
                    value={g.progress ?? 0}
                    label={g.progressMessage ?? (g.status === 'downloading' ? 'Downloading…' : 'Processing…')}
                  />
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

      {drive && (
        <div className="modal-backdrop" onClick={closeDrive}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            {drive.step === 'url' && (
              <>
                <h3>Import from Google Drive</h3>
                <p className="modal-hint">
                  Paste a file or folder link shared as <strong>"anyone with the link"</strong>.
                </p>
                <input
                  className="modal-input"
                  type="text"
                  placeholder="https://drive.google.com/…"
                  value={driveUrl}
                  autoFocus
                  onChange={(e) => setDriveUrl(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') submitDriveUrl()
                  }}
                />
                {driveError && <p className="modal-error">{driveError}</p>}
                <div className="actions">
                  <button className="btn" onClick={closeDrive}>Cancel</button>
                  <button className="btn btn-primary" onClick={submitDriveUrl} disabled={!driveUrl.trim()}>
                    Continue
                  </button>
                </div>
              </>
            )}

            {drive.step === 'loading' && (
              <div className="modal-loading">
                <span className="spinner" />
                <p>Looking in your Drive…</p>
              </div>
            )}

            {drive.step === 'pick' && (
              <>
                <h3>Choose videos to import</h3>
                {drive.files.map((f) => (
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
                {driveError && <p className="modal-error">{driveError}</p>}
                <div className="actions">
                  <button className="btn" onClick={closeDrive}>Cancel</button>
                  <button
                    className="btn btn-primary"
                    onClick={confirmDrivePick}
                    disabled={driveImporting || checked.size === 0}
                  >
                    {driveImporting ? 'Importing…' : `Import ${checked.size} video${checked.size === 1 ? '' : 's'}`}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
