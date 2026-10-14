import { useEffect, useRef, useState } from 'react'
import { mergeWorkouts, parseHistory, readResponse } from './workoutApi'
import type { WorkoutHistory as HistoryData } from './workoutApi'

const PAGE_SIZE = 20

function formatDuration(seconds: number) {
  return `${Math.floor(seconds / 60)}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`
}

export function WorkoutHistory({ connected, version }: { connected: boolean; version: number }) {
  const [history, setHistory] = useState<HistoryData | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [moreError, setMoreError] = useState<string | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [nextOffset, setNextOffset] = useState(0)
  const request = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    request.current?.abort()
    request.current = controller
    void Promise.resolve().then(async () => {
      if (controller.signal.aborted || !connected) return
      setLoading(true)
      setLoadingMore(false)
      setError(null)
      setMoreError(null)
      try {
        const response = await fetch(`/api/history?limit=${PAGE_SIZE}&offset=0`, { signal: controller.signal })
        const data = parseHistory(await readResponse(response, 'Workout history is unavailable. Try again in a moment.'))
        if (!controller.signal.aborted) {
          setNextOffset(data.workouts.length)
          setHistory(data)
        }
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Could not load workout history.')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    })
    return () => {
      controller.abort()
      request.current?.abort()
    }
  }, [connected, version, refresh])

  async function loadMore() {
    if (!connected || loading || loadingMore || !history) return
    const controller = new AbortController()
    request.current?.abort()
    request.current = controller
    setLoadingMore(true)
    setMoreError(null)
    try {
      const response = await fetch(`/api/history?limit=${PAGE_SIZE}&offset=${nextOffset}`, { signal: controller.signal })
      const data = parseHistory(await readResponse(response, 'Could not load older sets. Try again.'))
      if (!controller.signal.aborted) {
        setNextOffset((previous) => data.workouts.length === 0 ? data.total : previous + data.workouts.length)
        setHistory((previous) => ({ ...data, workouts: mergeWorkouts(previous?.workouts ?? [], data.workouts) }))
      }
    } catch (cause) {
      if (!controller.signal.aborted) setMoreError(cause instanceof Error ? cause.message : 'Could not load older sets.')
    } finally {
      if (!controller.signal.aborted) setLoadingMore(false)
    }
  }

  const hasMore = history !== null && nextOffset < history.total
  const summary = history?.summary

  return (
    <section className="history-section" aria-labelledby="history-title" aria-busy={connected && (loading || loadingMore)}>
      <div className="history-heading">
        <div><p className="eyebrow">KEEP SHOWING UP</p><h2 id="history-title">Your workout history</h2>
          <p className="history-subtitle">Completed sets are saved automatically. Every rep adds up.</p></div>
        <button className="text-button" disabled={!connected || loading || loadingMore} onClick={() => setRefresh((value) => value + 1)}>
          {loading ? 'Refreshing…' : 'Refresh history'}
        </button>
      </div>

      {!connected && <p className="history-message" role="status">Reconnect to the tracker to load your saved sets.</p>}
      {connected && loading && !history && <p className="history-message" role="status">Loading your workout history…</p>}
      {connected && error && <div className="history-message history-error" role="alert"><p>{error}</p>
        <button className="text-button" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>Try again</button></div>}

      {summary && <div className="history-summary" aria-label="Workout totals">
        <div><span className="tiny-label">COMPLETED SETS</span><strong>{summary.totalSets.toLocaleString()}</strong></div>
        <div><span className="tiny-label">TOTAL REPS</span><strong>{summary.totalReps.toLocaleString()}</strong></div>
        <div><span className="tiny-label">THIS WEEK · UTC</span><strong>{summary.weekReps.toLocaleString()}<span> reps</span></strong></div>
        <div><span className="tiny-label">BEST SET</span><strong>{summary.bestSet.toLocaleString()}<span> reps</span></strong></div>
      </div>}

      {history && history.workouts.length === 0 && !error && <div className="history-empty">
        <span aria-hidden="true">↗</span><h3>Your first set starts the story.</h3>
        <p>Reach your rep goal and your completed set will appear here.</p>
      </div>}

      {history && history.workouts.length > 0 && <>
        <div className="history-table-wrap">
          <table className="history-table">
            <caption className="sr-only">Completed push-up sets, newest first. Dates are shown in your local time.</caption>
            <thead><tr><th scope="col">Completed</th><th scope="col">Exercise</th><th scope="col">Reps</th><th scope="col">Active time</th></tr></thead>
            <tbody>{history.workouts.map((workout) => <tr key={workout.id}>
              <td><time dateTime={workout.completedAt}>{new Date(workout.completedAt).toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' })}</time></td>
              <td>Push-ups</td><td><strong>{workout.reps}</strong><span className="history-goal"> / {workout.goal}</span></td>
              <td className="duration-cell">{formatDuration(workout.durationSeconds)}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <div className="history-bottom">
          <span>{history.workouts.length} of {history.total} saved sets · Local time</span>
          {hasMore && <button className="text-button" disabled={!connected || loading || loadingMore} onClick={() => { void loadMore() }}>
            {loadingMore ? 'Loading…' : moreError ? 'Retry older sets' : 'Load older sets'}
          </button>}
        </div>
        {moreError && <p className="history-more-error error-text" role="alert">{moreError}</p>}
      </>}
    </section>
  )
}
