import type { DriveFile, EventType, Game, GameEvent } from './types'

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `Request failed (${res.status})`)
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
  patchEvent: (gameId: string, eventId: string, changes: { type?: EventType; timestamp?: number }) =>
    fetch(`/api/games/${gameId}/events/${eventId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(changes),
    }).then((r) => asJson<GameEvent>(r)),
  deleteEvent: (gameId: string, eventId: string) =>
    fetch(`/api/games/${gameId}/events/${eventId}`, { method: 'DELETE' }).then((r) =>
      asJson<{ ok: boolean }>(r),
    ),
  exportClip: async (gameId: string, eventId: string): Promise<Blob> => {
    const res = await fetch(`/api/games/${gameId}/events/${eventId}/export`, { method: 'POST' })
    if (!res.ok) throw new Error('Export failed')
    return res.blob()
  },
  videoUrl: (gameId: string) => `/api/games/${gameId}/video`,
  thumbUrl: (gameId: string, eventId: string) => `/api/games/${gameId}/events/${eventId}/thumb.jpg`,
}
