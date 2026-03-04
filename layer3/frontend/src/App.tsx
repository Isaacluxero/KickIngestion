import { useEffect, useState, useCallback, useRef } from 'react'
import { Clip, Stats } from './types'
import StatsBar from './components/StatsBar'
import ClipCard from './components/ClipCard'

type SortKey = 'score' | 'time' | 'streamer'

const DEFAULT_STATS: Stats = { pending: 0, approved: 0, rejected: 0, posted: 0 }

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 768)
  useEffect(() => {
    const handler = () => setIsMobile(window.innerWidth < 768)
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [])
  return isMobile
}

export default function App() {
  const [clips, setClips] = useState<Clip[]>([])
  const [stats, setStats] = useState<Stats>(DEFAULT_STATS)
  const [sort, setSort] = useState<SortKey>('score')
  const [bulkApproving, setBulkApproving] = useState(false)
  const isMobile = useIsMobile()

  // Stable refs so keyboard handler closure always sees latest data
  const sortedRef = useRef<Clip[]>([])

  const fetchClips = useCallback(async () => {
    try {
      const res = await fetch('/api/clips')
      if (res.ok) setClips(await res.json())
    } catch {}
  }, [])

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch('/api/stats')
      if (res.ok) setStats(await res.json())
    } catch {}
  }, [])

  useEffect(() => {
    fetchClips()
    fetchStats()
    const interval = setInterval(() => { fetchStats(); fetchClips() }, 30_000)
    return () => clearInterval(interval)
  }, [fetchClips, fetchStats])

  const handleApprove = useCallback(async (id: string, title: string, hashtags: string[]) => {
    await fetch(`/api/clips/${encodeURIComponent(id)}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, hashtags }),
    })
    setClips(cs => cs.filter(c => c.id !== id))
    fetchStats()
  }, [fetchStats])

  const handleReject = useCallback(async (id: string) => {
    await fetch(`/api/clips/${encodeURIComponent(id)}/reject`, { method: 'POST' })
    setClips(cs => cs.filter(c => c.id !== id))
    fetchStats()
  }, [fetchStats])

  const handleBulkApprove = async () => {
    setBulkApproving(true)
    try {
      await fetch('/api/bulk-approve', { method: 'POST' })
      await fetchClips()
      await fetchStats()
    } finally {
      setBulkApproving(false)
    }
  }

  const sorted = [...clips].sort((a, b) => {
    if (sort === 'score') return b.score - a.score
    if (sort === 'time') return b.timestamp - a.timestamp
    return a.streamer.localeCompare(b.streamer)
  })

  // Keep ref in sync for keyboard handler
  sortedRef.current = sorted

  // Keyboard shortcuts — desktop only
  useEffect(() => {
    if (isMobile) return
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      if (['INPUT', 'TEXTAREA'].includes(target?.tagName)) return

      const top = sortedRef.current[0]
      if (e.key === 'ArrowRight' && top) {
        handleApprove(top.id, top.suggested_title, top.suggested_hashtags)
      } else if (e.key === 'ArrowLeft' && top) {
        handleReject(top.id)
      } else if (e.key === ' ') {
        e.preventDefault()
        const video = document.querySelector<HTMLVideoElement>('video')
        if (video) video.paused ? video.play() : video.pause()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isMobile, handleApprove, handleReject])

  // ── MOBILE: one card at a time, full-screen ──────────────────────────────
  if (isMobile) {
    const activeClip = sorted[0]
    const remaining = sorted.length

    return (
      <div className="h-screen bg-gray-950 text-white flex flex-col overflow-hidden">
        {/* Progress bar */}
        <div className="flex-none px-4 pt-4 pb-2 flex items-center justify-between border-b border-gray-800">
          <span className="text-gray-400 text-sm font-medium">
            {remaining > 0
              ? `${remaining} clip${remaining !== 1 ? 's' : ''} remaining`
              : 'All done!'}
          </span>
          {remaining > 0 && (
            <span className="text-gray-600 text-xs">swipe to review</span>
          )}
        </div>

        {/* Single active card — scrollable vertically */}
        <div className="flex-1 overflow-y-auto px-4 py-4">
          {!activeClip ? (
            <div className="h-full flex flex-col items-center justify-center gap-3 text-center">
              <p className="text-4xl">🎉</p>
              <p className="text-gray-300 font-semibold">All clips reviewed!</p>
              <p className="text-gray-500 text-sm">Check back after the next stream.</p>
            </div>
          ) : (
            // key=activeClip.id ensures a fresh mount (and thus fresh swipe state)
            // when the top card changes
            <ClipCard
              key={activeClip.id}
              clip={activeClip}
              onApprove={handleApprove}
              onReject={handleReject}
              mobileActive
            />
          )}
        </div>
      </div>
    )
  }

  // ── DESKTOP: scrollable list ─────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <StatsBar stats={stats} onBulkApprove={handleBulkApprove} bulkApproving={bulkApproving} />

      <div className="max-w-2xl mx-auto px-4 py-6">
        {/* Sort controls + progress */}
        <div className="flex items-center gap-2 mb-6 flex-wrap">
          <span className="text-gray-500 text-sm">
            {sorted.length} remaining
          </span>
          <div className="ml-auto flex items-center gap-2 text-sm text-gray-400">
            <span>Sort:</span>
            {(['score', 'time', 'streamer'] as SortKey[]).map(key => (
              <button
                key={key}
                onClick={() => setSort(key)}
                className={`px-3 py-1 rounded-full transition-colors ${
                  sort === key
                    ? 'bg-blue-700 text-white'
                    : 'bg-gray-800 hover:bg-gray-700 text-gray-300'
                }`}
              >
                {key.charAt(0).toUpperCase() + key.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Keyboard hint */}
        <p className="text-gray-700 text-xs mb-4">
          ← reject · → approve · space = play/pause
        </p>

        {sorted.length === 0 ? (
          <div className="text-center text-gray-500 mt-20">
            <p className="text-xl">No clips pending review</p>
            <p className="text-sm mt-2">Clips appear here after the analyzer scores them.</p>
          </div>
        ) : (
          <div className="flex flex-col gap-6">
            {sorted.map(clip => (
              <ClipCard
                key={clip.id}
                clip={clip}
                onApprove={handleApprove}
                onReject={handleReject}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
