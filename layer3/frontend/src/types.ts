export interface Clip {
  id: string           // "{streamer}:{timestamp}"
  streamer: string
  timestamp: number
  score: number
  reason: string
  suggested_title: string
  suggested_hashtags: string[]
  hype_ratio: number
  msgs_per_sec: number
  clip_count: number
  file_path: string
  thumbnail_path: string | null
  transcript: string
  duration: number
  category: string
  priority: string
}

export interface Stats {
  pending: number
  approved: number
  rejected: number
  posted: number
}
