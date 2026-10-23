import assert from 'node:assert/strict'
import test from 'node:test'
import { initialStatus, isStatus } from '../src/trackerProtocol.ts'
import { calibrationGuidance, canChangeCalibration, trackingFeedback, trackingReasonMessage } from '../src/trackingFeedback.ts'
import { mergeWorkouts, parseCameras, parseHistory, readResponse } from '../src/workoutApi.ts'

// Small example responses let these checks run without a camera or database.
const status = { ...initialStatus, type: 'status', ackId: null }
const firstSet = { id: 'set-1', completedAt: '2026-10-13T14:30:00Z', reps: 10, goal: 10, durationSeconds: 34.5 }
const secondSet = { ...firstSet, id: 'set-2', completedAt: '2026-10-12T14:30:00Z' }
const history = { workouts: [firstSet], total: 1, summary: { totalSets: 1, totalReps: 10, weekReps: 10, bestSet: 10 } }

// Accept resting and paused plans while rejecting impossible timer values.
test('validates workout settings, set progress and rest timers', () => {
  const resting = { ...status, totalSets: 3, currentSet: 1, completedSets: 1,
    restSeconds: 90, restRemainingSeconds: 42, workoutState: 'resting', workoutElapsedSeconds: 25.4 }
  assert.equal(isStatus(resting), true)
  assert.equal(isStatus({ ...resting, workoutState: 'paused' }), true)
  assert.equal(isStatus({ ...resting, currentSet: 3, completedSets: 3, workoutState: 'complete', restRemainingSeconds: 0 }), true)
  for (const invalid of [
    { totalSets: 0 }, { totalSets: 11 }, { totalSets: true }, { currentSet: 0 }, { currentSet: 4 },
    { completedSets: 2 }, { completedSets: -1 }, { restSeconds: 301 }, { restSeconds: '60' },
    { restRemainingSeconds: 91 }, { restRemainingSeconds: -1 }, { restRemainingSeconds: 0.5 },
    { workoutState: 'done' }, { workoutElapsedSeconds: Infinity }, { workoutElapsedSeconds: -1 },
  ]) assert.equal(isStatus({ ...resting, ...invalid }), false, JSON.stringify(invalid))
})

// Between sets is still part of the same workout and must keep its calibration.
test('calibration stays locked during a multi set workout', () => {
  const betweenSets = { ...initialStatus, totalSets: 3, completedSets: 1, completed: true,
    historyState: 'saved' as const, workoutState: 'resting' as const }
  assert.equal(canChangeCalibration(betweenSets), false)
  assert.equal(canChangeCalibration({ ...betweenSets, workoutState: 'paused' }), false)
  assert.equal(canChangeCalibration({ ...initialStatus, workoutState: 'active' }), false)
})

// Valid updates must keep countdowns and save retries separate from active counting.
test('accepts backend countdown and save-retry status without treating them as a running set', () => {
  assert.equal(isStatus({ ...status, cameraState: 'ready', countdownSeconds: 5, running: false }), true)
  assert.equal(isStatus({ ...status, completed: true, historyState: 'error', historyError: 'History is unavailable.' }), true)
})

// Bad network values must be rejected before they can change the controls.
test('rejects corrupt status before it can replace workout controls', () => {
  for (const invalid of [
    { countdownSeconds: -1 }, { countdownSeconds: 6 }, { countdownSeconds: '5' },
    { cameraIndex: 0.5 }, { historyState: 'success' }, { historyVersion: Number.NaN },
    { historyError: {} }, { elapsedSeconds: Number.POSITIVE_INFINITY }, { ackId: '1' },
  ]) assert.equal(isStatus({ ...status, ...invalid }), false, JSON.stringify(invalid))
})

// Calibration can have partial angle information without pretending a joint is visible.
test('accepts calibration progress and missing angle estimates without inventing a position', () => {
  assert.equal(isStatus({ ...status, calibrationState: 'hold_up', calibrationProgress: 0.2,
    calibrationMessage: 'Hold at the top.', leftAngle: 169.4, rightAngle: null }), true)
  assert.equal(isStatus({ ...status, calibrationState: 'ready', calibrationProgress: 1,
    trackingQuality: 'valid', trackingReason: 'extend_arms', leftAngle: 0, rightAngle: 180 }), true)
})

// Check bounds and missing fields for the extra tracking information.
test('rejects malformed tracking quality, angle and calibration fields', () => {
  for (const invalid of [
    { trackingQuality: 'good' }, { trackingReason: 1 }, { leftAngle: undefined },
    { leftAngle: Number.NaN }, { leftAngle: -1 }, { rightAngle: 181 }, { rightAngle: Infinity },
    { calibrationState: 'finished' }, { calibrationProgress: -0.1 }, { calibrationProgress: 1.1 },
    { calibrationProgress: Number.NaN }, { calibrationProgress: '0.5' }, { calibrationMessage: null },
  ]) assert.equal(isStatus({ ...status, ...invalid }), false, JSON.stringify(invalid))
})

// A hidden joint can hold a rep briefly, while clear incorrect posture must restart it.
test('feedback distinguishes unreliable tracking from an invalid plank', () => {
  const running = { ...initialStatus, running: true, hasPose: true }
  const uncertain = trackingFeedback({ ...running, trackingQuality: 'uncertain', trackingReason: 'hips_not_visible', inGracePeriod: true })
  assert.equal(uncertain.phase, 'Holding your rep')
  assert.match(uncertain.guidance, /see your hips/)
  assert.match(uncertain.guidance, /counting waits for clear tracking/)
  const invalid = trackingFeedback({ ...running, trackingQuality: 'invalid', trackingReason: 'torso_too_upright', inGracePeriod: true })
  assert.equal(invalid.phase, 'Adjust your plank')
  assert.match(invalid.guidance, /Lower your hips/)
  assert.doesNotMatch(invalid.guidance, /rep is held/)
  const missing = trackingFeedback({ ...running, hasPose: false, trackingReason: 'no_pose' })
  assert.equal(missing.phase, 'Get in frame')
})

// Guidance must wait for a confirmed starting position before calling the arms up.
test('a valid plank without a confirmed stage does not claim an up position', () => {
  const ready = { ...initialStatus, running: true, hasPose: true, inPlank: true,
    trackingQuality: 'valid' as const, trackingReason: null }
  const starting = trackingFeedback(ready)
  assert.equal(starting.phase, 'Find your starting position')
  assert.match(starting.guidance, /hold briefly/)
  assert.equal(trackingFeedback({ ...ready, stage: 'up' }).phase, 'Up position')
  assert.equal(trackingFeedback({ ...ready, stage: 'down' }).phase, 'Down position')
})

// People should see useful words even when the backend adds a new reason code.
test('unknown reason codes produce useful fallback guidance instead of internal identifiers', () => {
  assert.equal(trackingReasonMessage(null), '')
  assert.equal(trackingReasonMessage('new_internal_reason'), 'Keep your arms and hips visible and move with control.')
  for (const reason of ['no_pose', 'world_landmarks_missing', 'shoulders_not_visible', 'elbows_not_visible',
    'wrists_not_visible', 'hips_not_visible', 'invalid_landmarks', 'borderline_posture',
    'torso_too_upright', 'face_camera', 'hands_not_below_shoulders', 'extend_arms', 'lower_body']) {
    assert.notEqual(trackingReasonMessage(reason), trackingReasonMessage('new_internal_reason'), reason)
  }
})

// Calibration feedback should explain missing body points without retaining old warnings.
test('calibration guidance includes the tracking problem only while a live practice step needs it', () => {
  const calibrating = { ...initialStatus, calibrationState: 'lower' as const, cameraState: 'ready' as const,
    calibrationMessage: 'Adjust your position until tracking is clear, then hold still.', trackingReason: 'hips_not_visible' }
  const message = calibrationGuidance(calibrating)
  assert.match(message, /Adjust your position/)
  assert.match(message, /see your hips/)
  assert.match(calibrationGuidance({ ...calibrating, trackingQuality: 'invalid', trackingReason: 'torso_too_upright' }), /Lower your hips/)
  assert.equal(calibrationGuidance({ ...calibrating, trackingQuality: 'valid' }), calibrating.calibrationMessage)
  assert.equal(calibrationGuidance({ ...calibrating, cameraState: 'starting' }), calibrating.calibrationMessage)
  assert.equal(calibrationGuidance({ ...calibrating, calibrationState: 'ready' }), calibrating.calibrationMessage)
  assert.equal(calibrationGuidance({ ...calibrating, trackingReason: null }), calibrating.calibrationMessage)
})

// Protect active or unsaved sets from a change in calibration thresholds.
test('calibration is available only for a fresh or saved set, never while counting or saving', () => {
  assert.equal(canChangeCalibration(initialStatus), true)
  assert.equal(canChangeCalibration({ ...initialStatus, calibrationState: 'ready' }), true)
  const saved = { ...initialStatus, completed: true, reps: 10, elapsedSeconds: 40, historyState: 'saved' as const }
  assert.equal(canChangeCalibration(saved), true)
  for (const unavailable of [
    { ...initialStatus, elapsedSeconds: 1 }, { ...initialStatus, reps: 1 },
    { ...initialStatus, running: true }, { ...initialStatus, countdownSeconds: 5 },
    { ...initialStatus, cameraState: 'starting' as const }, { ...initialStatus, cameraState: 'stopping' as const },
    { ...initialStatus, calibrationState: 'hold_up' as const },
    { ...initialStatus, calibrationState: 'lower' as const },
    { ...initialStatus, calibrationState: 'return_up' as const },
    { ...saved, historyState: 'saving' as const }, { ...saved, historyState: 'error' as const },
    { ...saved, historyState: null },
  ]) assert.equal(canChangeCalibration(unavailable), false, JSON.stringify(unavailable))
})

// Keep the real device indexes and handle computers with no available camera.
test('camera list preserves backend device indexes and supports an empty list', () => {
  const response = { cameras: [{ index: 3, name: 'USB Webcam' }], selectedIndex: 3 }
  assert.deepEqual(parseCameras(response), response)
  assert.deepEqual(parseCameras({ cameras: [], selectedIndex: 0 }).cameras, [])
  assert.throws(() => parseCameras({ cameras: [{ index: '3', name: 'USB Webcam' }], selectedIndex: 3 }))
  assert.throws(() => parseCameras({ cameras: [{ index: 1, name: '' }], selectedIndex: 1 }))
})

// Saved history needs usable dates and numbers before it can be displayed.
test('history uses server totals and rejects invalid dates and durations', () => {
  assert.deepEqual(parseHistory(history), history)
  assert.deepEqual(parseHistory({ ...history, workouts: [], total: 0 }).workouts, [])
  for (const invalid of [{ completedAt: 'not a date' }, { durationSeconds: -1 }, { durationSeconds: Infinity }, { reps: '10' }]) {
    assert.throws(() => parseHistory({ ...history, workouts: [{ ...firstSet, ...invalid }] }))
  }
  assert.throws(() => parseHistory({ ...history, summary: { ...history.summary, totalSets: null } }))
})

// Loading older results must not duplicate records or alter the previous list.
test('overlapping history pages do not duplicate sets after a new save moves the boundary', () => {
  const current = [firstSet]
  assert.deepEqual(mergeWorkouts(current, [firstSet, secondSet]), [firstSet, secondSet])
  assert.deepEqual(current, [firstSet], 'merging must not mutate the currently rendered page')
})

// A failed response needs an error message rather than an empty history screen.
test('failed history requests cannot become an empty success state', async () => {
  await assert.rejects(readResponse(new Response(JSON.stringify({ detail: 'Workout history is unavailable.' }), { status: 503 }), 'Fallback'), /Workout history is unavailable/)
  await assert.rejects(readResponse(new Response('Proxy unavailable', { status: 502 }), 'Could not load history.'), /Could not load history/)
  const data = await readResponse(new Response('not json', { status: 200 }), 'Fallback')
  assert.throws(() => parseHistory(data))
})
