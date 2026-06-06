import type { DriveFile, EventType, Game, GameEvent } from './types'

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body?.detail
    throw new Error(
      Array.isArray(detail)
        ? detail.map((d: { msg: string }) => d.msg).join('; ')
        : (detail ?? `Request failed (${res.status})`),
    )
  }
  return res.json()
}

const post = (url: string, body: unknown) =>
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const api = {
  listGames: () => fetch('/api/games').then((r) => asJson<Game[]>(r)),
  getGame: (id: string) => fetch(`/api/games/${id}`).then((r) => asJson<Game>(r)),
  deleteGame: (id: string) =>
    fetch(`/api/games/${id}`, { method: 'DELETE' }).then((r) => asJson<{ ok: boolean }>(r)),
  retryAnalysis: (id: string) =>
    fetch(`/api/games/${id}/process`, { method: 'POST' }).then((r) => asJson<{ job_id: string }>(r)),
  importFile: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch('/api/games/import', { method: 'POST', body: form }).then((r) => asJson<Game>(r))
  },
  listDriveFolder: (url: string) => post('/api/drive/list', { url }).then((r) => asJson<DriveFile[]>(r)),
  importDrive: (url: string, fileIds?: string[]) =>
    post('/api/games/import-drive', { url, fileIds }).then((r) => asJson<Game[]>(r)),
  listEvents: (gameId: string) =>
    fetch(`/api/games/${gameId}/events`).then((r) => asJson<GameEvent[]>(r)),
  createEvent: (gameId: string, type: EventType, timestamp: number) =>
    post(`/api/games/${gameId}/events`, { type, timestamp }).then((r) => asJson<GameEvent>(r)),
  patchEvent: (gameId: string, eventId: string, changes: { type?: EventType; timestamp?: number; verified?: boolean }) =>
    fetch(`/api/games/${gameId}/events/${eventId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(changes),
    }).then((r) => asJson<GameEvent>(r)),
  deleteEvent: (gameId: string, eventId: string) =>
    fetch(`/api/games/${gameId}/events/${eventId}`, { method: 'DELETE' }).then((r) =>
      asJson<{ ok: boolean }>(r),
    ),
  emailClip: (gameId: string, eventId: string, to: string) =>
    post(`/api/games/${gameId}/events/${eventId}/email`, { to }).then((r) => asJson<{ ok: boolean }>(r)),
  videoUrl: (gameId: string) => `/api/games/${gameId}/video`,
  thumbUrl: (gameId: string, eventId: string) => `/api/games/${gameId}/events/${eventId}/thumb.jpg`,
  clipUrl: (gameId: string, eventId: string) => `/api/games/${gameId}/events/${eventId}/clip.mp4`,
}
