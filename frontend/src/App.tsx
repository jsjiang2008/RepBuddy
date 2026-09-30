import { useState } from 'react'
import { useTracker } from './useTracker'
import type { CSSProperties } from 'react'
import './App.css'

function formatTime(milliseconds: number): string {
  const seconds = Math.floor(milliseconds / 1_000)
  return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`
}

function Mark({ small = false }: { small?: boolean }) {
  return (
    <svg className={small ? 'brand-mark small' : 'brand-mark'} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <path d="M5 18h5l4-10 5 17 4-10h4" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function App() {
  const { status: session, connected, pending, sendCommand, connectionError } = useTracker()
  const [previewVersion, setPreviewVersion] = useState(0)
  const [previewFailed, setPreviewFailed] = useState(false)
  const { reps, completed } = session
  const elapsedMs = session.elapsedSeconds * 1_000
  const progress = Math.min(100, Math.round((reps / session.goal) * 100))
  const busy = pending || session.cameraState === 'starting' || session.cameraState === 'stopping'
  const error = connectionError || session.commandError || session.error
  const phase = !connected ? 'Tracker offline'
    : error ? 'Tracking needs attention'
    : session.cameraState === 'starting' ? 'Opening camera…'
    : session.cameraState === 'stopping' ? 'Closing camera…'
    : completed ? 'Set complete'
    : !session.running ? (elapsedMs > 0 ? 'Session paused' : 'Ready to begin')
    : session.inGracePeriod ? 'Holding your rep'
    : !session.hasPose ? 'Get in frame'
    : !session.inPlank ? 'Get into plank'
    : session.stage === 'down' ? 'Down position' : 'Up position'
  const guidance = !connected ? 'Start the Python tracker. This screen reconnects automatically.'
    : error || (completed ? 'Set complete. Start a new set when you’re ready.'
    : session.inGracePeriod ? 'Brief tracking loss. Your rep is held for up to half a second.'
    : session.running ? 'Face the camera and keep your arms and hips visible.'
    : 'Press Start to open your camera. Pause keeps the preview on; Stop releases it.')

  return (
    <div className="app-shell">
      <a className="skip-link" href="#workout">Skip to workout</a>
      <header className="app-header">
        <a className="brand" href="#workout" aria-label="RepBuddy workout">
          <Mark /><span>rep<span className="brand-light">buddy</span><span className="brand-dot">.</span></span>
        </a>
        <span className="header-divider" />
        <span className="header-label">YOUR PERSONAL REP COUNTER</span>
        <span className="mode-badge"><span className="status-dot" /> {connected ? 'Tracker connected' : 'Tracker offline'}</span>
      </header>

      <main id="workout">
        <section className="intro" aria-labelledby="page-title">
          <div>
            <p className="eyebrow">A LITTLE STRONGER, EVERY DAY</p>
            <h1 id="page-title">Make every rep count<span>.</span></h1>
            <p className="intro-copy">One set. Full focus. Your next personal best starts here.</p>
          </div>
          <div className="exercise-tag">
            <span className="exercise-icon" aria-hidden="true">↗</span>
            <div><span className="tiny-label">TODAY’S MOVEMENT</span><strong>Push-ups</strong></div>
          </div>
        </section>

        <div className="connection-notice">
          <span className="notice-symbol" aria-hidden="true">i</span>
          <p role="status"><strong>{connected ? 'On-device tracking.' : 'Waiting for the tracker.'}</strong> {connected ? 'Your camera is processed locally. Press Start when you’re ready.' : 'Start the Python server to connect your camera and counter.'}</p>
        </div>

        <div className="workout-grid">
          <section className="preview-panel" aria-labelledby="preview-title">
            <div className="panel-heading"><h2 id="preview-title">Camera preview</h2><span className="muted-label">FRONT VIEW</span></div>
            <div className={`preview-stage ${session.running ? 'is-running' : ''}`}>
              <span className="preview-label"><span className="status-dot" /> {connected && session.cameraState === 'ready' ? 'LIVE CAMERA' : 'CAMERA OFF'}</span>
              <span className="preview-corner">01 / PUSH-UP</span>
              {connected && session.cameraState === 'ready' ? (
                <>
                  <img key={previewVersion} className="camera-feed" src={`/api/video?v=${previewVersion}`}
                    alt="Live workout camera with pose landmarks"
                    onLoad={() => setPreviewFailed(false)} onError={() => setPreviewFailed(true)} />
                  {previewFailed && <div className="camera-placeholder" role="alert">
                    <p>Camera preview interrupted.</p>
                    <button className="secondary-button" onClick={() => { setPreviewFailed(false); setPreviewVersion((value) => value + 1) }}>Retry preview</button>
                  </div>}
                </>
              ) : <div className="camera-placeholder"><Mark /><h3>{phase}</h3><p>{guidance}</p></div>}
              <div className="preview-caption"><span className="caption-line" /><span>Arms and hips in frame. Face the camera.</span></div>
            </div>
            <div className="tracking-strip">
              <span className={`tracking-icon ${session.running || completed ? 'active' : ''}`} aria-hidden="true">{completed ? '✓' : '◎'}</span>
              <div>
                <p className="tracking-title" role="status">{phase}</p>
                <p className="tracking-description">{guidance}</p>
              </div>
              <span className="tracking-pill">{session.running ? 'TRACKING' : 'IDLE'}</span>
            </div>
          </section>

          <section className="session-panel" aria-labelledby="session-title">
            <div className="panel-heading"><h2 id="session-title">Your set</h2><span className="set-badge">01</span></div>
            <div className="counter-ring" style={{ '--progress': `${progress}%` } as CSSProperties}>
              <div className="counter-inner">
                <span className="tiny-label">COMPLETED REPS</span>
                <span className="rep-number" aria-live="polite" aria-atomic="true">{reps.toString().padStart(2, '0')}</span>
                <span className="rep-target">of {session.goal} reps</span>
              </div>
            </div>
            <div className="goal-row">
              <label htmlFor="rep-goal">Rep goal</label>
              <select id="rep-goal" value={session.goal} disabled={!connected || busy || session.running || elapsedMs > 0} onChange={(event) => sendCommand('goal', Number(event.target.value))}>
                {[5, 10, 15, 20].map((goal) => <option key={goal} value={goal}>{goal} reps</option>)}
              </select>
            </div>
            <div className="session-stats">
              <div><span className="tiny-label">ACTIVE TIME</span><strong>{formatTime(elapsedMs)}</strong></div>
              <div><span className="tiny-label">SET PROGRESS</span><strong>{progress}<span className="stat-unit">%</span></strong></div>
            </div>
            <div className="session-actions">
              <button className="primary-button" disabled={!connected || busy} onClick={() => sendCommand(session.running ? 'pause' : 'start')}>
                <span aria-hidden="true">{session.running ? 'Ⅱ' : '▶'}</span>
                {busy ? 'Please wait…' : session.running ? 'Pause' : completed ? 'New set' : elapsedMs > 0 ? 'Resume' : 'Start'}
              </button>
              <button className="reset-button" onClick={() => sendCommand('reset')} disabled={!connected || busy} aria-label="Reset session" title="Reset session">↺</button>
            </div>
            <button className="stop-button" disabled={!connected || pending || session.cameraState === 'off' || session.cameraState === 'stopping'} onClick={() => sendCommand('stop')}>Stop camera</button>
            <p className="session-footnote">{elapsedMs > 0 ? 'Reset your set to change the rep goal.' : 'Set your goal. Then make your first move.'}</p>
          </section>
        </div>

        <section className="setup-section" aria-labelledby="setup-title">
          <div className="setup-heading"><p className="eyebrow">GET SET UP</p><h2 id="setup-title">Good form starts here.</h2></div>
          <ol className="setup-tips">
            <li><span className="tip-number">01</span><div><h3>Face forward</h3><p>Place your camera in front of you, approximately level.</p></div></li>
            <li><span className="tip-number">02</span><div><h3>Find your frame</h3><p>Keep your arms and hips visible. Knees and ankles are optional.</p></div></li>
            <li><span className="tip-number">03</span><div><h3>Move with control</h3><p>Start with arms extended. Lower, then push back up.</p></div></li>
          </ol>
        </section>
      </main>
      <footer className="app-footer"><span><Mark small /> BUILT FOR YOUR NEXT REP.</span><span>RepBuddy · Local workout tracking</span></footer>
    </div>
  )
}

export default App
