type CameraState = 'off' | 'starting' | 'ready' | 'stopping'

export type TrackerCommand =
  | { command: 'start' | 'pause' | 'stop' | 'reset' | 'retrySave' }
  | { command: 'goal'; goal: number }
  | { command: 'camera'; cameraIndex: number }

export type TrackerStatus = {
  reps: number
  goal: number
  stage: 'up' | 'down' | null
  running: boolean
  completed: boolean
  inPlank: boolean
  hasPose: boolean
  inGracePeriod: boolean
  elapsedSeconds: number
  cameraState: CameraState
  cameraIndex: number
  countdownSeconds: number
  historyState: null | 'saving' | 'saved' | 'error'
  historyError: string | null
  historyVersion: number
  error: string | null
  commandError: string | null
}

export const initialStatus: TrackerStatus = {
  reps: 0, goal: 10, stage: null, running: false, completed: false,
  inPlank: false, hasPose: false, inGracePeriod: false, elapsedSeconds: 0,
  cameraState: 'off', cameraIndex: 0, countdownSeconds: 0,
  historyState: null, historyError: null, historyVersion: 0,
  error: null, commandError: null,
}

export function isStatus(value: unknown): value is TrackerStatus & { type: 'status'; ackId: number | null } {
  if (!value || typeof value !== 'object') return false
  const data = value as Record<string, unknown>
  return data.type === 'status'
    && ['reps', 'cameraIndex', 'historyVersion', 'countdownSeconds'].every((key) =>
      typeof data[key] === 'number' && Number.isInteger(data[key]) && data[key] >= 0)
    && (data.countdownSeconds as number) <= 5
    && typeof data.goal === 'number' && [5, 10, 15, 20].includes(data.goal)
    && typeof data.elapsedSeconds === 'number' && Number.isFinite(data.elapsedSeconds) && data.elapsedSeconds >= 0
    && [null, 'up', 'down'].includes(data.stage as string | null)
    && ['off', 'starting', 'ready', 'stopping'].includes(data.cameraState as string)
    && [null, 'saving', 'saved', 'error'].includes(data.historyState as string | null)
    && ['running', 'completed', 'inPlank', 'hasPose', 'inGracePeriod'].every((key) => typeof data[key] === 'boolean')
    && ['error', 'commandError', 'historyError'].every((key) => data[key] === null || typeof data[key] === 'string')
    && (data.ackId === null || (typeof data.ackId === 'number' && Number.isInteger(data.ackId)))
}
