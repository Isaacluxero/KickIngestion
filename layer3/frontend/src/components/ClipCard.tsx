import { useState } from 'react'
import { Clip } from '../types'
import VideoPlayer from './VideoPlayer'

interface Props {
  clip: Clip
  onApprove: (id: string, title: string, hashtags: string[]) => Promise<void>
  onReject: (id: string) => Promise<void>
}

function ScoreBadge({ score }: { score: number }) {
  const cls =
    score >= 8
      ? 'bg-green-700 text-white'
      : score >= 6
      ? 'bg-yellow-600 text-white'
      : 'bg-red-700 text-white'
  return (
    <span className={`${cls} text-2xl font-bold px-4 py-1 rounded-full`}>
      {score}
    </span>
  )
}

export default function ClipCard({ clip, onApprove, onReject }: Props) {
  const [title, setTitle] = useState(clip.suggested_title)
  const [hashtags, setHashtags] = useState<string[]>(clip.suggested_hashtags)
  const [newTag, setNewTag] = useState('')
  const [transcriptOpen, setTranscriptOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [dismissed, setDismissed] = useState(false)

  if (dismissed) return null

  const handleApprove = async () => {
    setBusy(true)
    await onApprove(clip.id, title, hashtags)
    setDismissed(true)
  }

  const handleReject = async () => {
    setBusy(true)
    await onReject(clip.id)
    setDismissed(true)
  }

  const removeTag = (tag: string) => setHashtags(hashtags.filter(t => t !== tag))

  const addTag = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && newTag.trim()) {
      setHashtags([...hashtags, newTag.trim().replace(/^#/, '')])
      setNewTag('')
    }
  }

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <ScoreBadge score={clip.score} />
        <div>
          <div className="text-white font-semibold text-lg">{clip.streamer}</div>
          <div className="text-gray-400 text-sm">{clip.category}</div>
        </div>
      </div>

      {/* Reason */}
      <p className="text-gray-300 italic text-sm">{clip.reason}</p>

      {/* Video */}
      <VideoPlayer filePath={clip.file_path} />

      {/* Stats chips */}
      <div className="flex gap-3 text-sm text-gray-300 flex-wrap">
        <span>💬 {clip.msgs_per_sec.toFixed(0)} msg/s</span>
        <span>🔥 {(clip.hype_ratio * 100).toFixed(0)}% hype</span>
        <span>✂️ {clip.clip_count} clipped</span>
        <span>⏱ {clip.duration.toFixed(0)}s</span>
      </div>

      {/* Editable title */}
      <div>
        <label className="text-gray-400 text-xs mb-1 block">Title</label>
        <input
          value={title}
          onChange={e => setTitle(e.target.value)}
          className="w-full bg-gray-800 text-white border border-gray-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
        />
      </div>

      {/* Hashtag pills */}
      <div>
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
          onClick={handleApprove}
          disabled={busy}
          className="flex-1 bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white font-semibold py-2 rounded-lg transition-colors"
        >
          ✅ Approve
        </button>
        <button
          onClick={handleReject}
          disabled={busy}
          className="flex-1 bg-gray-700 hover:bg-red-800 disabled:opacity-50 text-white font-semibold py-2 rounded-lg transition-colors"
        >
          ❌ Reject
        </button>
      </div>
    </div>
  )
}
