import { useRef, useEffect, useState } from 'react'

interface Props {
  filePath: string
  autoPlay?: boolean
}

export default function VideoPlayer({ filePath, autoPlay = false }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [isMuted, setIsMuted] = useState(true)

  const src = filePath.startsWith('/clips') ? filePath : `/clips/${filePath}`

  // iOS requires muted=true for autoplay. React's `muted` prop has a known bug where
  // it doesn't update reactively, so we set it imperatively via the DOM ref.
  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    v.muted = true
    if (autoPlay) {
      v.play().catch(() => {})
    }
  }, [autoPlay])

  const unmute = () => {
    const v = videoRef.current
    if (!v) return
    v.muted = false
    setIsMuted(false)
  }

  return (
    <div className="relative w-full">
      <video
        ref={videoRef}
        src={src}
        controls
        playsInline
        className="w-full rounded-lg"
        style={{ maxHeight: '60vh' }}
      />
      {isMuted && autoPlay && (
        <button
          onClick={unmute}
          className="absolute bottom-12 right-2 bg-black/70 text-white text-xs px-3 py-1 rounded-full"
        >
          🔇 Tap to unmute
        </button>
      )}
    </div>
  )
}
