import { useEffect, useRef, useState } from 'react'
import { initialStatus, isStatus } from './trackerProtocol'
import type { TrackerCommand } from './trackerProtocol'

// A custom React hook keeps the live connection and workout state in one place.
export function useTracker() {
  // State changes cause React to update the screen.
  const [status, setStatus] = useState(initialStatus)
  const [connected, setConnected] = useState(false)
  const [pending, setPending] = useState(false)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  // Refs remember connection details without causing extra screen updates.
  const socketRef = useRef<WebSocket | null>(null)
  const nextRequestId = useRef(0)
  const pendingId = useRef<number | null>(null)
  const pendingSince = useRef(0)

  // This effect opens the connection when the screen loads and closes it on cleanup.
  useEffect(() => {
    let disposed = false
    let retry: number | undefined
    let lastMessage = performance.now()

    // WebSocket lets Python send live updates without repeated page requests.
    function connect() {
      if (disposed) return
      const url = new URL('/api/ws', window.location.href)
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
      const socket = new WebSocket(url)
      socketRef.current = socket
      lastMessage = performance.now()

      // Accept only valid updates from the current connection.
      socket.onmessage = (event: MessageEvent<string>) => {
        if (disposed || socketRef.current !== socket) return
        try {
          const data: unknown = JSON.parse(event.data)
          if (!isStatus(data)) throw new Error('Invalid tracking update')
          lastMessage = performance.now()
          setStatus(data)
          setConnected(true)
          setConnectionError(null)
          // Unlock the controls after Python confirms the matching command.
          if (pendingId.current !== null && data.ackId === pendingId.current) {
            pendingId.current = null
            setPending(false)
          }
        } catch {
          setConnectionError('Received an invalid tracking update. Reconnecting…')
          socket.close()
        }
      }
      socket.onerror = () => socket.close()
      // Show the tracker as stopped while waiting to reconnect.
      socket.onclose = () => {
        if (disposed || socketRef.current !== socket) return
        setConnected(false)
        setPending(false)
        pendingId.current = null
        setStatus((previous) => ({ ...previous, running: false, countdownSeconds: 0, cameraState: 'off' }))
        retry = window.setTimeout(connect, 1_500)
      }
    }

    connect()
    // Recover if updates stop arriving or a command is never confirmed.
    const watchdog = window.setInterval(() => {
      if (performance.now() - lastMessage > 5_000) socketRef.current?.close()
      if (pendingId.current !== null && performance.now() - pendingSince.current > 8_000) {
        pendingId.current = null
        setPending(false)
        setConnectionError('The tracker did not confirm your command. Reconnecting…')
        socketRef.current?.close()
      }
    }, 1_000)

    // Cleanup prevents old timers and connections from updating a removed screen.
    return () => {
      disposed = true
      window.clearTimeout(retry)
      window.clearInterval(watchdog)
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [])

  // Send one command at a time and attach a number for its acknowledgement.
  function sendCommand(command: TrackerCommand) {
    const socket = socketRef.current
    if (!connected || !socket || socket.readyState !== WebSocket.OPEN || pendingId.current !== null) return
    const requestId = ++nextRequestId.current
    pendingId.current = requestId
    pendingSince.current = performance.now()
    setPending(true)
    socket.send(JSON.stringify({ ...command, requestId }))
  }

  return { status, connected, pending, sendCommand, connectionError }
}
