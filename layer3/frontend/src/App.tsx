import { useEffect, useState, useCallback } from 'react'
import { Clip, Stats } from './types'
import StatsBar from './components/StatsBar'
import ClipCard from './components/ClipCard'

type SortKey = 'score' | 'time' | 'streamer'

const DEFAULT_STATS: Stats = { pending: 0, approved: 0, rejected: 0, posted: 0 }

export default function App() {
  const [clips, setClips] = useState<Clip[]>([])
  const [stats, setStats] = useState<Stats>(DEFAULT_STATS)
  const [sort, setSort] = useState<SortKey>('score')
  const [bulkApproving, setBulkApproving] = useState(false)

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

  const handleApprove = async (id: string, title: string, hashtags: string[]) => {
    await fetch(`/api/clips/${encodeURIComponent(id)}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, hashtags }),
    })
    setClips(cs => cs.filter(c => c.id !== id))
    fetchStats()
  }

  const handleReject = async (id: string) => {
    await fetch(`/api/clips/${encodeURIComponent(id)}/reject`, { method: 'POST' })
    setClips(cs => cs.filter(c => c.id !== id))
    fetchStats()
  }

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

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <StatsBar stats={stats} onBulkApprove={handleBulkApprove} bulkApproving={bulkApproving} />

      <div className="max-w-2xl mx-auto px-4 py-6">
        {/* Sort controls */}
        <div className="flex items-center gap-2 mb-6 text-sm text-gray-400">
          <span>Sort by:</span>
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

        {/* Clip list */}
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
