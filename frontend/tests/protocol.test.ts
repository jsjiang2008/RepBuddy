import assert from 'node:assert/strict'
import test from 'node:test'
import { initialStatus, isStatus } from '../src/trackerProtocol.ts'
import { mergeWorkouts, parseCameras, parseHistory, readResponse } from '../src/workoutApi.ts'

const status = { ...initialStatus, type: 'status', ackId: null }
const firstSet = { id: 'set-1', completedAt: '2026-10-13T14:30:00Z', reps: 10, goal: 10, durationSeconds: 34.5 }
const secondSet = { ...firstSet, id: 'set-2', completedAt: '2026-10-12T14:30:00Z' }
const history = { workouts: [firstSet], total: 1, summary: { totalSets: 1, totalReps: 10, weekReps: 10, bestSet: 10 } }

test('accepts backend countdown and save-retry status without treating them as a running set', () => {
  assert.equal(isStatus({ ...status, cameraState: 'ready', countdownSeconds: 5, running: false }), true)
  assert.equal(isStatus({ ...status, completed: true, historyState: 'error', historyError: 'History is unavailable.' }), true)
})

test('rejects corrupt status before it can replace workout controls', () => {
  for (const invalid of [
    { countdownSeconds: -1 }, { countdownSeconds: 6 }, { countdownSeconds: '5' },
    { cameraIndex: 0.5 }, { historyState: 'success' }, { historyVersion: Number.NaN },
    { historyError: {} }, { elapsedSeconds: Number.POSITIVE_INFINITY }, { ackId: '1' },
  ]) assert.equal(isStatus({ ...status, ...invalid }), false, JSON.stringify(invalid))
})

test('camera list preserves backend device indexes and supports an empty list', () => {
  const response = { cameras: [{ index: 3, name: 'USB Webcam' }], selectedIndex: 3 }
  assert.deepEqual(parseCameras(response), response)
  assert.deepEqual(parseCameras({ cameras: [], selectedIndex: 0 }).cameras, [])
  assert.throws(() => parseCameras({ cameras: [{ index: '3', name: 'USB Webcam' }], selectedIndex: 3 }))
  assert.throws(() => parseCameras({ cameras: [{ index: 1, name: '' }], selectedIndex: 1 }))
})

test('history uses server totals and rejects invalid dates and durations', () => {
  assert.deepEqual(parseHistory(history), history)
  assert.deepEqual(parseHistory({ ...history, workouts: [], total: 0 }).workouts, [])
  for (const invalid of [{ completedAt: 'not a date' }, { durationSeconds: -1 }, { durationSeconds: Infinity }, { reps: '10' }]) {
    assert.throws(() => parseHistory({ ...history, workouts: [{ ...firstSet, ...invalid }] }))
  }
  assert.throws(() => parseHistory({ ...history, summary: { ...history.summary, totalSets: null } }))
})

test('overlapping history pages do not duplicate sets after a new save moves the boundary', () => {
  const current = [firstSet]
  assert.deepEqual(mergeWorkouts(current, [firstSet, secondSet]), [firstSet, secondSet])
  assert.deepEqual(current, [firstSet], 'merging must not mutate the currently rendered page')
})

test('failed history requests cannot become an empty success state', async () => {
  await assert.rejects(readResponse(new Response(JSON.stringify({ detail: 'Workout history is unavailable.' }), { status: 503 }), 'Fallback'), /Workout history is unavailable/)
  await assert.rejects(readResponse(new Response('Proxy unavailable', { status: 502 }), 'Could not load history.'), /Could not load history/)
  const data = await readResponse(new Response('not json', { status: 200 }), 'Fallback')
  assert.throws(() => parseHistory(data))
})
