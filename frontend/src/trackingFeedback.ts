import type { TrackerStatus } from './trackerProtocol.ts'

// Turn short backend reason codes into useful instructions for the person exercising.
const reasonMessages: Record<string, string> = {
  no_pose: 'Move into frame so your arms and hips are visible.',
  world_landmarks_missing: 'The camera cannot judge your position yet. Keep your arms and hips in view.',
  shoulders_not_visible: 'Keep both shoulders in view.',
  elbows_not_visible: 'Move back slightly so both elbows stay in view.',
  wrists_not_visible: 'Keep both hands in frame throughout the movement.',
  hips_not_visible: 'Move back slightly so the camera can see your hips.',
  invalid_landmarks: 'Your position is unclear. Hold still briefly with your arms and hips visible.',
  borderline_posture: 'Your plank position is unclear. Hold steady with your body straight.',
  torso_too_upright: 'Lower your hips into a plank with your body straight.',
  face_camera: 'Face the camera with both shoulders in view.',
  hands_not_below_shoulders: 'Place your hands beneath your shoulders in a plank.',
  extend_arms: 'Extend both arms and hold briefly at the top.',
  lower_body: 'Lower your body until both elbows bend fully.',
}

// Keep a helpful message even if a newer backend sends an unfamiliar reason.
export function trackingReasonMessage(reason: string | null): string {
  return reason ? reasonMessages[reason] ?? 'Keep your arms and hips visible and move with control.' : ''
}

// Only the three movement steps mean calibration is still in progress.
export function isCalibrating(session: Pick<TrackerStatus, 'calibrationState'>): boolean {
  return ['hold_up', 'lower', 'return_up'].includes(session.calibrationState)
}

// Explain which body points or posture need attention while calibration is waiting.
export function calibrationGuidance(session: TrackerStatus): string {
  const reason = isCalibrating(session) && session.cameraState === 'ready' && session.trackingQuality !== 'valid'
    ? trackingReasonMessage(session.trackingReason) : ''
  return [session.calibrationMessage, reason].filter(Boolean).join(' ')
}

// Changing thresholds during a set would make its reps inconsistent.
// Allow calibration before a fresh set or after the previous set is saved.
export function canChangeCalibration(session: TrackerStatus): boolean {
  const freshSet = !session.completed && session.reps === 0 && session.elapsedSeconds === 0
  const savedSet = session.completed && session.historyState === 'saved'
  return (freshSet || savedSet) && !session.running && session.countdownSeconds === 0
    && (session.workoutState === 'idle' || session.workoutState === 'complete')
    && session.cameraState !== 'starting' && session.cameraState !== 'stopping'
    && session.historyState !== 'saving' && session.historyState !== 'error' && !isCalibrating(session)
}

// Choose a short status and a next step from the latest tracking result.
export function trackingFeedback(session: TrackerStatus): { phase: string; guidance: string } {
  if (!session.running) return {
    phase: session.elapsedSeconds > 0 ? 'Session paused' : 'Ready to begin',
    guidance: 'Press Start to open your camera. Pause keeps the preview on; Stop releases it.',
  }

  const reason = trackingReasonMessage(session.trackingReason)
  // An unclear view can hold a rep briefly, but it must never count a movement.
  if (session.trackingQuality === 'uncertain') return {
    phase: session.inGracePeriod ? 'Holding your rep' : session.hasPose ? 'Tracking is unclear' : 'Get in frame',
    guidance: `${reason || 'Keep your arms and hips visible.'} ${session.inGracePeriod
      ? 'Your rep is held briefly; counting waits for clear tracking.'
      : 'Counting waits for clear tracking.'}`,
  }
  // Clear evidence of incorrect posture requires a new starting position.
  if (session.trackingQuality === 'invalid') return {
    phase: 'Adjust your plank',
    guidance: `${reason || 'Return to a straight plank facing the camera.'} Start again with both arms extended.`,
  }
  // A plank alone does not confirm that the arms reached the top position.
  if (session.stage === null) return {
    phase: 'Find your starting position',
    guidance: reason || 'Extend both arms and hold briefly at the top to begin.',
  }
  return {
    phase: session.stage === 'down' ? 'Down position' : 'Up position',
    guidance: reason || (session.stage === 'down' ? 'Push back up and extend both arms.' : 'Lower with control, then push back up.'),
  }
}
