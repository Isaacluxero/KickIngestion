import { useState, useRef } from 'react'
import { useSwipeable } from 'react-swipeable'
import { Clip } from '../types'
import VideoPlayer from './VideoPlayer'

interface Props {
  clip: Clip
  onApprove: (id: string, title: string, hashtags: string[]) => Promise<void>
  onReject: (id: string) => Promise<void>
  /** True when this is the active card in mobile one-at-a-time mode */
  mobileActive?: boolean
}

function ScoreBadge({ score }: { score: number }) {
  const cls =
    score >= 8 ? 'bg-green-700 text-white' :
    score >= 6 ? 'bg-yellow-600 text-white' :
    'bg-red-700 text-white'
  return (
    <span className={`${cls} text-2xl font-bold px-4 py-1 rounded-full`}>{score}</span>
  )
}

const SWIPE_THRESHOLD = 0.4 // fraction of card width to trigger action

export default function ClipCard({ clip, onApprove, onReject, mobileActive = false }: Props) {
  const [title, setTitle] = useState(clip.suggested_title)
  const [hashtags, setHashtags] = useState<string[]>(clip.suggested_hashtags)
  const [newTag, setNewTag] = useState('')
  const [transcriptOpen, setTranscriptOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [dismissed, setDismissed] = useState(false)

  // Swipe animation state
  const [dragX, setDragX] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const [flyingOut, setFlyingOut] = useState<'left' | 'right' | null>(null)

  const cardRef = useRef<HTMLDivElement>(null)

  const triggerApprove = () => {
    if (busy || flyingOut) return
    setBusy(true)
    setDragX(0)
    setFlyingOut('right')
    // Wait for fly-out animation, then call parent
    setTimeout(() => {
      onApprove(clip.id, title, hashtags)
    }, 280)
  }

  const triggerReject = () => {
    if (busy || flyingOut) return
    setBusy(true)
    setDragX(0)
    setFlyingOut('left')
    setTimeout(() => {
      onReject(clip.id)
    }, 280)
  }

  const swipeHandlers = useSwipeable({
    onSwiping: ({ deltaX }) => {
      if (flyingOut || busy) return
      const w = cardRef.current?.offsetWidth ?? 320
      setDragX(Math.max(-w, Math.min(w, deltaX)))
      setIsDragging(true)
    },
    onSwipedRight: ({ deltaX }) => {
      setIsDragging(false)
      const w = cardRef.current?.offsetWidth ?? 320
      if (deltaX >= w * SWIPE_THRESHOLD) {
        triggerApprove()
      } else {
        setDragX(0) // snap back
      }
    },
    onSwipedLeft: ({ deltaX }) => {
      setIsDragging(false)
      const w = cardRef.current?.offsetWidth ?? 320
      if (-deltaX >= w * SWIPE_THRESHOLD) {
        triggerReject()
      } else {
        setDragX(0) // snap back
      }
    },
    onSwiped: ({ dir }) => {
      // Snap back for vertical swipes
      if (dir === 'Up' || dir === 'Down') {
        setIsDragging(false)
        setDragX(0)
      }
    },
    trackMouse: true,
    preventScrollOnSwipe: false,
    delta: 10,
  })

  if (dismissed) return null

  const cardWidth = cardRef.current?.offsetWidth ?? 320
  const approveOpacity = dragX > 0 ? Math.min(dragX / (cardWidth * SWIPE_THRESHOLD), 1) : 0
  const rejectOpacity = dragX < 0 ? Math.min(-dragX / (cardWidth * SWIPE_THRESHOLD), 1) : 0

  const cardStyle: React.CSSProperties = flyingOut
    ? {
        transform: `translateX(${flyingOut === 'right' ? '150%' : '-150%'}) rotate(${flyingOut === 'right' ? '20' : '-20'}deg)`,
        transition: 'transform 0.3s ease',
        pointerEvents: 'none',
      }
    : isDragging
    ? {
        transform: `translateX(${dragX}px) rotate(${(dragX / cardWidth) * 15}deg)`,
        transition: 'none',
      }
    : {
        transform: 'none',
        transition: 'transform 0.3s ease',
      }

  const removeTag = (tag: string) => setHashtags(h => h.filter(t => t !== tag))

  const addTag = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && newTag.trim()) {
      setHashtags(h => [...h, newTag.trim().replace(/^#/, '')])
      setNewTag('')
    }
  }

  return (
    <div
      ref={cardRef}
      style={cardStyle}
      className="relative bg-gray-900 border border-gray-700 rounded-xl p-4 flex flex-col gap-4 select-none"
      {...swipeHandlers}
    >
      {/* APPROVE overlay — visible while swiping right */}
      {approveOpacity > 0 && (
        <div
          style={{ opacity: approveOpacity }}
          className="absolute inset-0 rounded-xl bg-green-600/20 border-4 border-green-500 flex items-center justify-start pl-6 z-10 pointer-events-none"
        >
          <span className="text-green-400 text-3xl font-black" style={{ transform: 'rotate(-15deg)' }}>
            ✅ APPROVE
          </span>
        </div>
      )}

      {/* REJECT overlay — visible while swiping left */}
      {rejectOpacity > 0 && (
        <div
          style={{ opacity: rejectOpacity }}
          className="absolute inset-0 rounded-xl bg-red-600/20 border-4 border-red-500 flex items-center justify-end pr-6 z-10 pointer-events-none"
        >
          <span className="text-red-400 text-3xl font-black" style={{ transform: 'rotate(15deg)' }}>
            ❌ REJECT
          </span>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center gap-3">
        <ScoreBadge score={clip.score} />
        <div>
          <div className="text-white font-semibold text-lg">{clip.streamer}</div>
          <div className="text-gray-400 text-sm">{clip.category}</div>
        </div>
      </div>

      {/* LLM reason */}
      <p className="text-gray-300 italic text-sm">{clip.reason}</p>

      {/* Video */}
      <VideoPlayer filePath={clip.file_path} autoPlay={mobileActive} />

      {/* Stat chips */}
      <div className="flex gap-3 text-sm text-gray-300 flex-wrap">
        <span>💬 {clip.msgs_per_sec.toFixed(0)} msg/s</span>
        <span>🔥 {(clip.hype_ratio * 100).toFixed(0)}% hype</span>
        <span>✂️ {clip.clip_count} clipped</span>
        <span>⏱ {clip.duration.toFixed(0)}s</span>
      </div>

      {/* Editable title — stopPropagation on pointer so dragging inside the input doesn't trigger card swipe */}
      <div onPointerDown={e => e.stopPropagation()}>
        <label className="text-gray-400 text-xs mb-1 block">Title</label>
        <input
          value={title}
          onChange={e => setTitle(e.target.value)}
          className="w-full bg-gray-800 text-white border border-gray-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
        />
      </div>

      {/* Hashtag pills */}
      <div onPointerDown={e => e.stopPropagation()}>
        <label className="text-gray-400 text-xs mb-1 block">Hashtags</label>
        <div className="flex flex-wrap gap-2 mb-2">
          {hashtags.map(tag => (
            <button
              key={tag}
              onClick={() => removeTag(tag)}
              className="bg-gray-700 hover:bg-red-800 text-gray-200 text-xs px-2 py-1 rounded-full transition-colors"
            >
              #{tag} ×
            </button>
          ))}
        </div>
        <input
          value={newTag}
          onChange={e => setNewTag(e.target.value)}
          onKeyDown={addTag}
          placeholder="Add tag (Enter)"
          className="bg-gray-800 text-white border border-gray-600 rounded-lg px-3 py-1 text-sm focus:outline-none focus:border-blue-500"
        />
      </div>

      {/* Transcript toggle */}
      <div>
        <button
          onClick={() => setTranscriptOpen(o => !o)}
          className="text-gray-500 hover:text-gray-300 text-xs underline"
        >
          {transcriptOpen ? 'Hide' : 'Show'} transcript
        </button>
        {transcriptOpen && (
          <p className="mt-2 text-gray-400 text-xs leading-relaxed bg-gray-800 rounded-lg p-3">
            {clip.transcript || '(no transcript)'}
          </p>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex gap-3">
        <button
          onClick={triggerApprove}
          disabled={busy}
          className="flex-1 bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white font-semibold py-2 rounded-lg transition-colors"
        >
          ✅ Approve
        </button>
        <button
          onClick={triggerReject}
          disabled={busy}
          className="flex-1 bg-gray-700 hover:bg-red-800 disabled:opacity-50 text-white font-semibold py-2 rounded-lg transition-colors"
        >
          ❌ Reject
        </button>
      </div>
    </div>
  )
}
