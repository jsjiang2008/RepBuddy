import { useEffect, useState } from 'react'
import { parseCameras, readResponse } from './workoutApi'
import type { Camera } from './workoutApi'

// Props are the values and callback supplied by the main workout screen.
// The callback passes a selected camera index back to that screen.
type Props = {
  connected: boolean
  selectedIndex: number
  canChange: boolean
  onChange: (index: number) => void
}

export function CameraPicker({ connected, selectedIndex, canChange, onChange }: Props) {
  // State holds the device list and the messages shown while it loads.
  const [cameras, setCameras] = useState<Camera[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [refresh, setRefresh] = useState(0)

  // Reload after a connection change or a refresh click.
  // Cancelling an old request stops it from replacing a newer result.
  useEffect(() => {
    const controller = new AbortController()
    void Promise.resolve().then(async () => {
      if (controller.signal.aborted || !connected) return
      setLoading(true)
      setError(null)
      try {
        const response = await fetch('/api/cameras', { signal: controller.signal })
        const data = parseCameras(await readResponse(response, 'Could not find your cameras. Try refreshing the list.'))
        if (!controller.signal.aborted) setCameras(data.cameras)
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Could not load cameras.')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    })
    return () => controller.abort()
  }, [connected, refresh])

  // Explain why the menu is unavailable or why another camera must be chosen.
  const selectedAvailable = cameras.some((camera) => camera.index === selectedIndex)
  const description = !connected ? 'Connect to the tracker to choose a camera.'
    : loading ? 'Looking for cameras…'
    : error ? error
    : cameras.length === 0 ? 'No cameras found. Connect a webcam, then refresh.'
    : !canChange ? 'Stop the camera before switching devices.'
    : !selectedAvailable ? 'The selected camera is unavailable. Choose another device.'
    : 'Choose the webcam you want to use for this set.'

  // Render the device menu, refresh button, and a message for screen readers.
  return (
    <div className="camera-controls">
      <div className="camera-picker-row">
        <label htmlFor="camera-device">Camera</label>
        <select id="camera-device" value={selectedAvailable ? selectedIndex : ''}
          disabled={!connected || !canChange || loading || cameras.length === 0}
          aria-describedby="camera-help" onChange={(event) => onChange(Number(event.target.value))}>
          {!selectedAvailable && <option value="" disabled>{loading ? 'Finding cameras…' : 'Choose a camera'}</option>}
          {cameras.map((camera) => <option key={camera.index} value={camera.index}>{camera.name}</option>)}
        </select>
        <button className="text-button" disabled={!connected || loading} onClick={() => setRefresh((value) => value + 1)}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>
      <p id="camera-help" className={error ? 'field-help error-text' : 'field-help'} role={error ? 'alert' : 'status'}>{description}</p>
    </div>
  )
}
