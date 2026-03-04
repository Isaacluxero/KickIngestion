interface Props {
  filePath: string
}

export default function VideoPlayer({ filePath }: Props) {
  // file_path is like "/clips/xqc/1234.mp4" — strip leading "/clips" to match the backend route
  const src = filePath.startsWith('/clips')
    ? filePath
    : `/clips/${filePath}`

  return (
    <video
      src={src}
      controls
      className="w-full rounded-lg"
      style={{ maxHeight: '60vh' }}
    />
  )
}
