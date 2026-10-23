// Types describe the camera list and saved workout data used by React.
export type Camera = { index: number; name: string }
export type CameraList = { cameras: Camera[]; selectedIndex: number }
export type Workout = { id: string; completedAt: string; reps: number; goal: number; durationSeconds: number }
export type WorkoutHistory = {
  workouts: Workout[]
  total: number
  summary: { totalSets: number; totalReps: number; weekReps: number; bestSet: number }
}

// These small checks help reject missing fields and invalid numbers.
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

// Check the camera response before filling the device menu.
export function parseCameras(value: unknown): CameraList {
  if (!isRecord(value) || !isCount(value.selectedIndex) || !Array.isArray(value.cameras)
    || !value.cameras.every((camera: unknown) => isRecord(camera) && isCount(camera.index)
      && typeof camera.name === 'string' && camera.name.trim().length > 0)) {
    throw new Error('The camera list could not be read. Try refreshing it.')
  }
  return value as CameraList
}

// Check dates, totals, and durations before displaying saved sets.
export function parseHistory(value: unknown): WorkoutHistory {
  if (!isRecord(value) || !isCount(value.total) || !isRecord(value.summary)
    || !['totalSets', 'totalReps', 'weekReps', 'bestSet'].every((key) => isCount(value.summary && (value.summary as Record<string, unknown>)[key]))
    || !Array.isArray(value.workouts) || !value.workouts.every((workout: unknown) =>
      isRecord(workout) && typeof workout.id === 'string' && workout.id.length > 0
      && typeof workout.completedAt === 'string' && Number.isFinite(Date.parse(workout.completedAt))
      && isCount(workout.reps) && isCount(workout.goal) && workout.goal > 0
      && typeof workout.durationSeconds === 'number' && Number.isFinite(workout.durationSeconds)
      && workout.durationSeconds >= 0)) {
    throw new Error('Your workout history could not be read. Try refreshing it.')
  }
  return value as WorkoutHistory
}

// Combine pages by workout ID so a new save cannot make a set appear twice.
export function mergeWorkouts(current: Workout[], next: Workout[]): Workout[] {
  return [...new Map([...current, ...next].map((workout) => [workout.id, workout])).values()]
}

// Read the response and show a useful error instead of treating a failed request as empty data.
export async function readResponse(response: Response, fallback: string): Promise<unknown> {
  const data: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(isRecord(data) && typeof data.detail === 'string' ? data.detail : fallback)
  }
  return data
}
