import { Stats } from '../types'

interface Props {
  stats: Stats
  onBulkApprove: () => void
  bulkApproving: boolean
}

export default function StatsBar({ stats, onBulkApprove, bulkApproving }: Props) {
  return (
    <div className="sticky top-0 z-10 bg-gray-900 border-b border-gray-700 px-4 py-3 flex items-center gap-6 flex-wrap">
      <span className="text-sm font-medium text-gray-200">
        <span className="text-yellow-400 font-bold">{stats.pending}</span> pending
      </span>
      <span className="text-sm font-medium text-gray-200">
        <span className="text-green-400 font-bold">{stats.approved}</span> approved
      </span>
      <span className="text-sm font-medium text-gray-200">
        <span className="text-red-400 font-bold">{stats.rejected}</span> rejected
      </span>
      <span className="text-sm font-medium text-gray-200">
        <span className="text-blue-400 font-bold">{stats.posted}</span> posted
      </span>

      <div className="ml-auto">
        <button
          onClick={onBulkApprove}
          disabled={bulkApproving}
          className="bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
        >
          {bulkApproving ? 'Approving…' : 'Approve All 8+'}
        </button>
      </div>
    </div>
  )
}
