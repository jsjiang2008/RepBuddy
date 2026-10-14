import { useEffect, useRef, useState } from 'react'
import { initialStatus, isStatus } from './trackerProtocol'
import type { TrackerCommand } from './trackerProtocol'

export function useTracker() {
  const [status, setStatus] = useState(initialStatus)
  const [connected, setConnected] = useState(false)
  const [pending, setPending] = useState(false)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const nextRequestId = useRef(0)
  const pendingId = useRef<number | null>(null)
  const pendingSince = useRef(0)

  useEffect(() => {
    let disposed = false
    let retry: number | undefined
    let lastMessage = performance.now()

    function connect() {
      if (disposed) return
      const url = new URL('/api/ws', window.location.href)
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
      const socket = new WebSocket(url)
      socketRef.current = socket
      lastMessage = performance.now()

      socket.onmessage = (event: MessageEvent<string>) => {
        if (disposed || socketRef.current !== socket) return
        try {
          const data: unknown = JSON.parse(event.data)
          if (!isStatus(data)) throw new Error('Invalid tracking update')
          lastMessage = performance.now()
          setStatus(data)
          setConnected(true)
          setConnectionError(null)
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
    const watchdog = window.setInterval(() => {
      if (performance.now() - lastMessage > 5_000) socketRef.current?.close()
      if (pendingId.current !== null && performance.now() - pendingSince.current > 8_000) {
        pendingId.current = null
        setPending(false)
        setConnectionError('The tracker did not confirm your command. Reconnecting…')
        socketRef.current?.close()
      }
    }, 1_000)

    return () => {
      disposed = true
      window.clearTimeout(retry)
      window.clearInterval(watchdog)
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [])

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
