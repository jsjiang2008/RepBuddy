import { useState } from 'react'
import { useTracker } from './useTracker'
import { CameraPicker } from './CameraPicker'
import { WorkoutHistory } from './WorkoutHistory'
import { calibrationGuidance, canChangeCalibration, isCalibrating, trackingFeedback, trackingReasonMessage } from './trackingFeedback'
import type { CSSProperties } from 'react'
import './App.css'

// Convert active time into a fixed width display of minutes and seconds.
function formatTime(milliseconds: number): string {
  const seconds = Math.floor(milliseconds / 1_000)
  return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`
}

// Reuse the same small logo in the header, camera placeholder, and footer.
function Mark({ small = false }: { small?: boolean }) {
  return (
    <svg className={small ? 'brand-mark small' : 'brand-mark'} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <path d="M5 18h5l4-10 5 17 4-10h4" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function App() {
  // The tracker hook supplies live Python data and a callback for sending commands.
  const { status: session, connected, pending, sendCommand, connectionError } = useTracker()
  // Local React state lets the camera preview be retried without resetting the set.
  const [previewVersion, setPreviewVersion] = useState(0)
  const [previewFailed, setPreviewFailed] = useState(false)
  const { reps, completed } = session
  // Derive display values from the backend so the screen does not count reps itself.
  const progress = Math.min(100, Math.round((reps / session.goal) * 100))
  const countingDown = connected && session.countdownSeconds > 0
  const resting = connected && session.workoutState === 'resting'
  const betweenSets = session.completedSets === session.currentSet && session.completedSets < session.totalSets
  const restPaused = session.workoutState === 'paused' && betweenSets
  const workoutComplete = session.workoutState === 'complete'
  const canPause = session.running || countingDown || resting
  const calibrating = connected && isCalibrating(session)
  // Disable actions that could interrupt camera setup, calibration, or an unsaved set.
  const busy = pending || (session.cameraState === 'starting' && !countingDown) || session.cameraState === 'stopping'
  const savePending = session.historyState === 'saving' || session.historyState === 'error'
  const settingsLocked = !connected || busy || calibrating || savePending || session.workoutState !== 'idle'
  const canCalibrate = connected && !busy && canChangeCalibration(session)
  const error = connectionError || session.commandError || session.error
  const feedback = trackingFeedback(session)
  const calibrationMessage = calibrationGuidance(session)
  // Connection and camera problems take priority over normal movement guidance.
  const phase = !connected ? 'Tracker offline'
    : error ? 'Tracking needs attention'
    : session.cameraState === 'starting' ? 'Opening camera…'
    : session.cameraState === 'stopping' ? 'Closing camera…'
    : countingDown ? `Starting in ${session.countdownSeconds}…`
    : calibrating ? 'Calibrating your movement'
    : resting ? 'Take a breather'
    : restPaused ? 'Rest paused'
    : workoutComplete ? 'Workout complete'
    : feedback.phase
  const guidance = !connected ? 'Waiting for the tracker. This screen reconnects automatically.'
    : error || (countingDown ? 'Get into position. Counting begins when the countdown ends.'
    : calibrating ? calibrationMessage
    : resting ? (savePending && session.restRemainingSeconds === 0 ? 'Waiting for this set to save before continuing.' : `Set ${session.currentSet} complete. Set ${session.currentSet + 1} starts after rest and a five-second countdown.`)
    : restPaused ? 'Your rest timer is paused. Resume when you’re ready.'
    : workoutComplete ? (savePending ? 'All sets complete. Waiting for the last set to save.' : `You finished ${session.totalSets} ${session.totalSets === 1 ? 'set' : 'sets'} and ${session.totalSets * session.goal} reps. Nice work.`)
    : feedback.guidance)

  return (
    <div className="app-shell">
      <a className="skip-link" href="#workout">Skip to workout</a>
      {/* The header shows the app name and whether the Python tracker is connected. */}
      <header className="app-header">
        <a className="brand" href="#workout" aria-label="RepBuddy workout">
          <Mark /><span>rep<span className="brand-light">buddy</span><span className="brand-dot">.</span></span>
        </a>
        <span className="header-divider" />
        <span className="header-label">YOUR PERSONAL REP COUNTER</span>
        <span className="mode-badge"><span className="status-dot" /> {connected ? 'Tracker connected' : 'Tracker offline'}</span>
      </header>

      <main id="workout">
        {/* Introduce the exercise and explain how the camera is used. */}
        <section className="intro" aria-labelledby="page-title">
          <div>
            <p className="eyebrow">A LITTLE STRONGER, EVERY DAY</p>
            <h1 id="page-title">Make every rep count<span>.</span></h1>
            <p className="intro-copy">Your workout. Your pace. Make time for your next personal best.</p>
          </div>
          <div className="exercise-tag">
            <span className="exercise-icon" aria-hidden="true">↗</span>
            <div><span className="tiny-label">TODAY’S MOVEMENT</span><strong>Push-ups</strong></div>
          </div>
        </section>

        <div className="connection-notice">
          <span className="notice-symbol" aria-hidden="true">i</span>
          <p role="status"><strong>{connected ? 'On-device tracking.' : 'Waiting for the tracker.'}</strong> {connected ? 'Your camera is processed locally. You’ll have five seconds to get into position.' : 'Run the app to connect your camera and counter.'}</p>
        </div>

        <div className="workout-grid">
          <section className="preview-panel" aria-labelledby="preview-title">
            <div className="panel-heading"><h2 id="preview-title">Camera preview</h2><span className="muted-label">FRONT VIEW</span></div>
            {/* Camera selection sends the backend device index through the live connection. */}
            <CameraPicker connected={connected} selectedIndex={session.cameraIndex}
              canChange={!pending && session.cameraState === 'off'}
              onChange={(cameraIndex) => sendCommand({ command: 'camera', cameraIndex })} />
            <div className={`preview-stage ${session.running ? 'is-running' : ''}`}>
              <span className="preview-label"><span className="status-dot" /> {connected && session.cameraState === 'ready' ? 'LIVE CAMERA' : 'CAMERA OFF'}</span>
              <span className="preview-corner">01 / PUSH-UP</span>
              {/* Python supplies the video with pose markers already drawn on each frame. */}
              {connected && session.cameraState === 'ready' ? (
                <>
                  <img key={`${session.cameraIndex}-${previewVersion}`} className="camera-feed" src={`/api/video?v=${session.cameraIndex}-${previewVersion}`}
                    alt="Live workout camera with pose landmarks"
                    onLoad={() => setPreviewFailed(false)} onError={() => setPreviewFailed(true)} />
                  {previewFailed && <div className="camera-placeholder" role="alert">
                    <p>Camera preview interrupted.</p>
                    <button className="secondary-button" onClick={() => { setPreviewFailed(false); setPreviewVersion((value) => value + 1) }}>Retry preview</button>
                  </div>}
                </>
              ) : <div className="camera-placeholder"><Mark /><h3>{phase}</h3><p>{guidance}</p></div>}
              {/* Display the countdown reported by Python so both sides start together. */}
              {countingDown && !previewFailed && <div className="countdown-overlay" role="status" aria-live="polite" aria-atomic="true">
                <span className="countdown-label">GET INTO POSITION</span>
                <strong>{session.countdownSeconds}</strong>
                <span>Arms extended. Ready for your first rep.</span>
              </div>}
              {/* Rest stays separate from the countdown and does not add active time. */}
              {(resting || (connected && restPaused)) && !previewFailed && <div className="countdown-overlay rest-overlay">
                <span className="countdown-label">{restPaused ? 'REST PAUSED' : 'REST BETWEEN SETS'}</span>
                <strong role="timer" aria-label="Rest remaining">{formatTime(session.restRemainingSeconds * 1_000)}</strong>
                <span>Next up, set {session.currentSet + 1} of {session.totalSets}</span>
              </div>}
              <div className="preview-caption"><span className="caption-line" /><span>Arms and hips in frame. Face the camera.</span></div>
            </div>
            {/* Explain the current position and offer details when tracking is unclear. */}
            <div className="tracking-strip">
              <span className={`tracking-icon ${session.running || completed || calibrating ? 'active' : ''}`} aria-hidden="true">{completed && !calibrating ? '✓' : '◎'}</span>
              <div>
                <p className="tracking-title" role="status">{phase}</p>
                <p className="tracking-description">{guidance}</p>
                {connected && session.cameraState === 'ready' && <details className="tracking-details">
                  <summary>Tracking details</summary>
                  <dl>
                    <div><dt>Left elbow</dt><dd>{session.leftAngle === null ? 'Not visible' : `${Math.round(session.leftAngle)}°`}</dd></div>
                    <div><dt>Right elbow</dt><dd>{session.rightAngle === null ? 'Not visible' : `${Math.round(session.rightAngle)}°`}</dd></div>
                    <div><dt>Position</dt><dd>{session.trackingQuality === 'valid' ? 'Clear' : session.trackingQuality === 'uncertain' ? 'Unclear' : 'Adjust plank'}</dd></div>
                  </dl>
                  {session.trackingReason && <p>{trackingReasonMessage(session.trackingReason)}</p>}
                </details>}
              </div>
              <span className="tracking-pill">{calibrating ? 'CALIBRATING' : countingDown ? 'GET READY' : resting ? 'REST' : session.running ? 'TRACKING' : 'IDLE'}</span>
            </div>
            {/* Calibration guides one practice movement while the workout remains paused. */}
            <div className={`calibration-card ${calibrating ? 'is-calibrating' : ''}`}>
              <div className="calibration-heading">
                <h3>Tune your tracking <span>OPTIONAL</span></h3>
                <span className={`calibration-badge ${session.calibrationState === 'ready' ? 'is-ready' : ''}`}>
                  {calibrating ? 'In progress' : session.calibrationState === 'ready' ? 'Calibrated' : 'Default settings'}
                </span>
              </div>
              <p className="calibration-message" role="status">{calibrating || session.calibrationState === 'ready'
                ? calibrationMessage
                : 'Calibrate with one controlled push-up to adjust tracking for your camera position.'}</p>
              {calibrating ? <>
                <ol className="calibration-steps" aria-label="Calibration steps">
                  {([['hold_up', 'Hold at top'], ['lower', 'Lower'], ['return_up', 'Return to top']] as const).map(([state, label], index) =>
                    <li key={state} aria-current={session.calibrationState === state ? 'step' : undefined}>
                      <span>{index + 1}</span>{label}
                    </li>)}
                </ol>
                <progress className="calibration-progress" max={1} value={session.calibrationProgress} aria-label="Calibration progress" />
                <div className="calibration-actions">
                  <p>The timer and rep counter stay paused.</p>
                  <button className="text-button" disabled={pending || session.cameraState === 'stopping'} onClick={() => sendCommand({ command: 'cancelCalibration' })}>Cancel calibration</button>
                </div>
              </> : <div className="calibration-actions">
                <p>{session.workoutState !== 'idle' && !workoutComplete
                  ? 'Reset your workout before calibrating.'
                  : 'Keep the same camera position after calibration.'}</p>
                <div className="calibration-buttons">
                  {session.calibrationState === 'ready' && <button className="text-button" disabled={!canCalibrate} onClick={() => sendCommand({ command: 'clearCalibration' })}>Use defaults</button>}
                  <button className="text-button" disabled={!canCalibrate} onClick={() => sendCommand({ command: 'calibrate' })}>{session.calibrationState === 'ready' ? 'Recalibrate' : 'Calibrate'}</button>
                </div>
              </div>}
            </div>
          </section>

          {/* Show the backend rep count, goal, active time, and workout controls. */}
          <section className="session-panel" aria-labelledby="session-title">
            <div className="panel-heading"><h2 id="session-title">Your workout</h2><span className="set-badge">Set {session.currentSet} / {session.totalSets}</span></div>
            {/* The custom CSS value fills the ring according to the completed percentage. */}
            <div className="counter-ring" style={{ '--progress': `${progress}%` } as CSSProperties}>
              <div className="counter-inner">
                <span className="tiny-label">COMPLETED REPS</span>
                <span className="rep-number" aria-live="polite" aria-atomic="true">{reps.toString().padStart(2, '0')}</span>
                <span className="rep-target">of {session.goal} reps</span>
              </div>
            </div>
            <div className="goal-row">
              <label htmlFor="rep-goal">Reps per set</label>
              <select id="rep-goal" value={session.goal} disabled={settingsLocked} onChange={(event) => sendCommand({ command: 'goal', goal: Number(event.target.value) })}>
                {[5, 10, 15, 20].map((goal) => <option key={goal} value={goal}>{goal} reps</option>)}
              </select>
            </div>
            {/* Apply plan changes before starting so every set uses the same settings. */}
            <div className="goal-row">
              <label htmlFor="workout-sets">Number of sets</label>
              <select id="workout-sets" value={session.totalSets} disabled={settingsLocked} onChange={(event) => sendCommand({ command: 'configureWorkout', sets: Number(event.target.value), restSeconds: session.restSeconds })}>
                {Array.from({ length: 10 }, (_, i) => i + 1).map((sets) => <option key={sets} value={sets}>{sets} {sets === 1 ? 'set' : 'sets'}</option>)}
              </select>
            </div>
            <div className="goal-row">
              <label htmlFor="rest-time">Rest between sets</label>
              <select id="rest-time" value={session.restSeconds} disabled={settingsLocked || session.totalSets === 1} onChange={(event) => sendCommand({ command: 'configureWorkout', sets: session.totalSets, restSeconds: Number(event.target.value) })}>
                {[0, 15, 30, 45, 60, 90, 120, 180, 240, 300].map((seconds) => <option key={seconds} value={seconds}>{seconds === 0 ? 'No rest' : formatTime(seconds * 1_000)}</option>)}
                {![0, 15, 30, 45, 60, 90, 120, 180, 240, 300].includes(session.restSeconds) && <option value={session.restSeconds}>{formatTime(session.restSeconds * 1_000)}</option>}
              </select>
            </div>
            <p className="workout-summary">{session.totalSets * session.goal} planned reps · {session.completedSets} of {session.totalSets} sets complete</p>
            <div className="session-stats">
              <div><span className="tiny-label">ACTIVE TIME</span><strong>{formatTime(session.workoutElapsedSeconds * 1_000)}</strong></div>
              <div><span className="tiny-label">SET PROGRESS</span><strong>{progress}<span className="stat-unit">%</span></strong></div>
            </div>
            {/* Buttons send commands and wait for confirmation before allowing another action. */}
            <div className="session-actions">
              <button className="primary-button" disabled={!connected || busy || calibrating || (savePending && !canPause)} onClick={() => sendCommand({ command: canPause ? 'pause' : 'start' })}>
                <span aria-hidden="true">{countingDown ? '×' : canPause ? 'Ⅱ' : '▶'}</span>
                {busy ? 'Please wait…' : countingDown ? 'Cancel countdown' : resting ? 'Pause rest' : session.running ? 'Pause' : restPaused ? 'Resume rest' : workoutComplete ? 'New workout' : session.workoutState === 'paused' ? 'Resume' : 'Start workout'}
              </button>
              <button className="reset-button" onClick={() => sendCommand({ command: 'reset' })} disabled={!connected || busy || savePending} aria-label="Reset session" title="Reset session">↺</button>
            </div>
            {resting && <button className="skip-rest-button text-button" disabled={busy || savePending} onClick={() => sendCommand({ command: 'skipRest' })}>Skip rest</button>}
            <button className="stop-button" disabled={!connected || pending || session.cameraState === 'off' || session.cameraState === 'stopping'} onClick={() => sendCommand({ command: 'stop' })}>Stop camera</button>
            {/* A failed save stays visible so the completed set can be retried. */}
            {session.historyState && <div className={`save-notice ${session.historyState === 'error' ? 'save-error' : ''}`} role={session.historyState === 'error' ? 'alert' : 'status'}>
              <p>{session.historyState === 'saving' ? 'Saving your completed set…'
                : session.historyState === 'saved' ? '✓ Set saved to your history.'
                : session.historyError || 'Your set could not be saved. Retry to keep it in your history.'}</p>
              {session.historyState === 'error' && <button className="text-button" disabled={!connected || pending} onClick={() => sendCommand({ command: 'retrySave' })}>Retry saving set</button>}
            </div>}
            <p className="session-footnote">{countingDown ? 'The timer starts after the countdown.' : session.workoutState !== 'idle' ? 'Reset your workout to change its settings.' : session.totalSets === 1 ? 'Choose your reps and sets to get started.' : 'Each set starts automatically after rest and a countdown.'}</p>
          </section>
        </div>

        {/* These tips explain how to keep the required body points visible. */}
        <section className="setup-section" aria-labelledby="setup-title">
          <div className="setup-heading"><p className="eyebrow">GET SET UP</p><h2 id="setup-title">Good form starts here.</h2></div>
          <ol className="setup-tips">
            <li><span className="tip-number">01</span><div><h3>Face forward</h3><p>Place your camera in front of you, approximately level.</p></div></li>
            <li><span className="tip-number">02</span><div><h3>Find your frame</h3><p>Keep your arms and hips visible. Knees and ankles are optional.</p></div></li>
            <li><span className="tip-number">03</span><div><h3>Move with control</h3><p>Start with arms extended. Lower, then push back up.</p></div></li>
          </ol>
        </section>

        {/* A new history version tells the saved workout list to refresh. */}
        <WorkoutHistory connected={connected} version={session.historyVersion} />
      </main>
      <footer className="app-footer"><span><Mark small /> BUILT FOR YOUR NEXT REP.</span><span>RepBuddy · Local workout tracking</span></footer>
    </div>
  )
}

export default App
