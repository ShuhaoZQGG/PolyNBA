import type { OrderSchema } from '../../api/types'
import { useCancelOrder } from '../../api/hooks'
import DataTable, { type Column } from '../common/DataTable'

interface OrdersTableProps {
  orders: OrderSchema[]
  showCancel?: boolean
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    })
  } catch {
    return iso
  }
}

function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase()
  const colors =
    s === 'live' || s === 'open'
      ? 'bg-blue-100 text-blue-700'
      : s === 'filled' || s === 'matched'
      ? 'bg-green-100 text-green-700'
      : s === 'cancelled' || s === 'canceled'
      ? 'bg-gray-100 text-gray-500'
      : 'bg-amber-100 text-amber-700'

  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${colors}`}>
      {status}
    </span>
  )
}

function CancelButton({ orderId }: { orderId: string }) {
  const cancelOrder = useCancelOrder()

  const canCancel = !cancelOrder.isPending

  return (
    <button
      onClick={() => cancelOrder.mutate(orderId)}
      disabled={!canCancel}
      className="px-2.5 py-1 text-xs font-medium text-red-600 border border-red-200 rounded-lg hover:bg-red-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
    >
      {cancelOrder.isPending ? '...' : 'Cancel'}
    </button>
  )
}

export default function OrdersTable({ orders, showCancel = true }: OrdersTableProps) {
  const columns: Column<OrderSchema>[] = [
    {
      key: 'created',
      header: 'Time',
      render: (row) => (
        <span className="text-xs text-gray-500">{formatTime(row.created_at)}</span>
      ),
    },
    {
      key: 'side',
      header: 'Side',
      render: (row) => (
        <span
          className={`text-xs font-semibold ${
            row.side.toUpperCase() === 'BUY' ? 'text-green-600' : 'text-red-600'
          }`}
        >
          {row.side.toUpperCase()}
        </span>
      ),
    },
    {
      key: 'filled',
      header: 'Filled',
      render: (row) => (
        <span className="text-xs tabular-nums font-medium text-gray-800">
          {Math.round(row.filled_size)} / {Math.round(row.size)}
        </span>
      ),
    },
    {
      key: 'price',
      header: 'Price',
      render: (row) => (
        <span className="text-xs font-mono font-medium text-gray-700">
          {Math.round(row.price * 100)}&#162;
        </span>
      ),
    },
    {
      key: 'total',
      header: 'Total',
      render: (row) => (
        <span className="text-xs tabular-nums text-gray-500">
          ${(row.size * row.price).toFixed(2)}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row) => <StatusBadge status={row.status} />,
    },
    ...(showCancel
      ? [
          {
            key: 'actions',
            header: '',
            render: (row: OrderSchema) => {
              const s = row.status.toLowerCase()
              if (s === 'live' || s === 'open') {
                return <CancelButton orderId={row.order_id} />
              }
              return null
            },
          },
        ]
      : []),
  ]

  return (
    <DataTable
      columns={columns}
      data={orders}
      rowKey={(row) => row.order_id}
      emptyMessage="No orders yet"
    />
  )
}
