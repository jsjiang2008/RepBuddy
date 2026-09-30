import { useEffect, useRef, useState } from 'react'

type CameraState = 'off' | 'starting' | 'ready' | 'stopping'
type Command = 'start' | 'pause' | 'stop' | 'reset' | 'goal'

export type TrackerStatus = {
  reps: number
  goal: number
  stage: 'up' | 'down' | null
  running: boolean
  completed: boolean
  inPlank: boolean
  hasPose: boolean
  inGracePeriod: boolean
  elapsedSeconds: number
  cameraState: CameraState
  error: string | null
  commandError: string | null
}

const initialStatus: TrackerStatus = {
  reps: 0, goal: 10, stage: null, running: false, completed: false,
  inPlank: false, hasPose: false, inGracePeriod: false, elapsedSeconds: 0,
  cameraState: 'off', error: null, commandError: null,
}

function isStatus(value: unknown): value is TrackerStatus & { type: 'status'; ackId: number | null } {
  if (!value || typeof value !== 'object') return false
  const data = value as Record<string, unknown>
  return data.type === 'status'
    && typeof data.reps === 'number' && Number.isInteger(data.reps) && data.reps >= 0
    && typeof data.goal === 'number' && [5, 10, 15, 20].includes(data.goal)
    && typeof data.elapsedSeconds === 'number' && Number.isFinite(data.elapsedSeconds) && data.elapsedSeconds >= 0
    && [null, 'up', 'down'].includes(data.stage as string | null)
    && ['off', 'starting', 'ready', 'stopping'].includes(data.cameraState as string)
    && ['running', 'completed', 'inPlank', 'hasPose', 'inGracePeriod'].every((key) => typeof data[key] === 'boolean')
    && ['error', 'commandError'].every((key) => data[key] === null || typeof data[key] === 'string')
    && (data.ackId === null || (typeof data.ackId === 'number' && Number.isInteger(data.ackId)))
}

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
        setStatus((previous) => ({ ...previous, running: false, cameraState: 'off' }))
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

  function sendCommand(command: Command, goal?: number) {
    const socket = socketRef.current
    if (!connected || !socket || socket.readyState !== WebSocket.OPEN || pendingId.current !== null) return
    const requestId = ++nextRequestId.current
    pendingId.current = requestId
    pendingSince.current = performance.now()
    setPending(true)
    socket.send(JSON.stringify({ command, goal, requestId }))
  }

  return { status, connected, pending, sendCommand, connectionError }
}
