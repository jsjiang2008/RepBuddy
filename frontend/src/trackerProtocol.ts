// These types describe the messages shared with the Python tracker.
type CameraState = 'off' | 'starting' | 'ready' | 'stopping'

// Each command allows only the extra information that command needs.
export type TrackerCommand =
  | { command: 'start' | 'pause' | 'stop' | 'reset' | 'retrySave' | 'calibrate' | 'cancelCalibration' | 'clearCalibration' | 'skipRest' }
  | { command: 'configureWorkout'; sets: number; restSeconds: number }
  | { command: 'goal'; goal: number }
  | { command: 'camera'; cameraIndex: number }

// A status message contains everything needed to update the workout screen.
export type TrackerStatus = {
  reps: number
  goal: number
  stage: 'up' | 'down' | null
  running: boolean
  completed: boolean
  inPlank: boolean
  hasPose: boolean
  inGracePeriod: boolean
  // Quality separates a clear plank, an unclear view, and incorrect posture.
  trackingQuality: 'valid' | 'uncertain' | 'invalid'
  trackingReason: string | null
  leftAngle: number | null
  rightAngle: number | null
  // Calibration follows one practice movement without counting it as a rep.
  calibrationState: 'idle' | 'hold_up' | 'lower' | 'return_up' | 'ready'
  calibrationProgress: number
  calibrationMessage: string
  elapsedSeconds: number
  cameraState: CameraState
  cameraIndex: number
  countdownSeconds: number
  // The backend owns set changes and the rest timer, including paused rest.
  totalSets: number
  currentSet: number
  completedSets: number
  restSeconds: number
  restRemainingSeconds: number
  workoutState: 'idle' | 'active' | 'resting' | 'paused' | 'complete'
  workoutElapsedSeconds: number
  // The history version changes after a save so the list knows to refresh.
  historyState: null | 'saving' | 'saved' | 'error'
  historyError: string | null
  historyVersion: number
  error: string | null
  commandError: string | null
}

// Use safe starting values until the backend sends its first status.
export const initialStatus: TrackerStatus = {
  reps: 0, goal: 10, stage: null, running: false, completed: false,
  inPlank: false, hasPose: false, inGracePeriod: false, elapsedSeconds: 0,
  trackingQuality: 'uncertain', trackingReason: 'no_pose', leftAngle: null, rightAngle: null,
  calibrationState: 'idle', calibrationProgress: 0, calibrationMessage: '',
  cameraState: 'off', cameraIndex: 0, countdownSeconds: 0,
  totalSets: 1, currentSet: 1, completedSets: 0, restSeconds: 60,
  restRemainingSeconds: 0, workoutState: 'idle', workoutElapsedSeconds: 0,
  historyState: null, historyError: null, historyVersion: 0,
  error: null, commandError: null,
}

// TypeScript types do not check network data. Validate every field before using it.
// The acknowledgement number tells the screen which command has finished.
export function isStatus(value: unknown): value is TrackerStatus & { type: 'status'; ackId: number | null } {
  if (!value || typeof value !== 'object') return false
  const data = value as Record<string, unknown>
  return data.type === 'status'
    && ['reps', 'cameraIndex', 'historyVersion', 'countdownSeconds'].every((key) =>
      typeof data[key] === 'number' && Number.isInteger(data[key]) && data[key] >= 0)
    && (data.countdownSeconds as number) <= 5
    && ['totalSets', 'currentSet', 'completedSets', 'restSeconds', 'restRemainingSeconds'].every((key) =>
      typeof data[key] === 'number' && Number.isInteger(data[key]) && data[key] >= 0)
    && (data.totalSets as number) >= 1 && (data.totalSets as number) <= 10
    && (data.currentSet as number) >= 1 && (data.currentSet as number) <= (data.totalSets as number)
    && (data.completedSets as number) <= (data.currentSet as number)
    && (data.restSeconds as number) <= 300 && (data.restRemainingSeconds as number) <= (data.restSeconds as number)
    && ['idle', 'active', 'resting', 'paused', 'complete'].includes(data.workoutState as string)
    && typeof data.workoutElapsedSeconds === 'number' && Number.isFinite(data.workoutElapsedSeconds) && data.workoutElapsedSeconds >= 0
    && typeof data.goal === 'number' && [5, 10, 15, 20].includes(data.goal)
    && typeof data.elapsedSeconds === 'number' && Number.isFinite(data.elapsedSeconds) && data.elapsedSeconds >= 0
    && [null, 'up', 'down'].includes(data.stage as string | null)
    && ['off', 'starting', 'ready', 'stopping'].includes(data.cameraState as string)
    && [null, 'saving', 'saved', 'error'].includes(data.historyState as string | null)
    && ['valid', 'uncertain', 'invalid'].includes(data.trackingQuality as string)
    && ['leftAngle', 'rightAngle'].every((key) => data[key] === null ||
      (typeof data[key] === 'number' && Number.isFinite(data[key]) && data[key] >= 0 && data[key] <= 180))
    && ['idle', 'hold_up', 'lower', 'return_up', 'ready'].includes(data.calibrationState as string)
    && typeof data.calibrationProgress === 'number' && Number.isFinite(data.calibrationProgress)
    && data.calibrationProgress >= 0 && data.calibrationProgress <= 1
    && typeof data.calibrationMessage === 'string'
    && ['running', 'completed', 'inPlank', 'hasPose', 'inGracePeriod'].every((key) => typeof data[key] === 'boolean')
    && ['error', 'commandError', 'historyError', 'trackingReason'].every((key) => data[key] === null || typeof data[key] === 'string')
    && (data.ackId === null || (typeof data.ackId === 'number' && Number.isInteger(data.ackId)))
}
