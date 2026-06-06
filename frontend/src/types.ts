export type EventType = 'shot' | 'goal'

export interface GameEvent {
  id: string
  type: EventType
  timestamp: number
  source: 'manual' | 'sample' | 'ai'
  clipStart: number
  clipEnd: number
}

export interface Game {
  id: string
  title: string
  date: string
  durationSec: number
  source: { kind: 'local' | 'drive'; url: string | null }
  status: 'downloading' | 'processing' | 'ready' | 'error'
  error: string | null
  goals?: number // present on GET /api/games
  shots?: number
}

export interface DriveFile {
  id: string
  name: string
}
