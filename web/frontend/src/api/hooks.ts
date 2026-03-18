import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { fetchApi, postJson, deleteApi, ApiError } from './client'
import type {
  PortfolioResponse,
  PositionsResponse,
  GameSummary,
  GameMarketSummary,
  GameAdvisoryResponse,
  OrderSchema,
  OrderRequest,
  OrderResponse,
  TradeHistoryResponse,
  PregameDatesResponse,
  PregameOrdersResponse,
  PregameOrder,
  RecordPregameOrderRequest,
} from './types'

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const queryKeys = {
  portfolio: ['portfolio'] as const,
  positions: ['positions'] as const,
  games: (date?: string) => ['games', date ?? 'today'] as const,
  markets: (date?: string) => ['markets', date ?? 'today'] as const,
  analysis: (gameId: string) => ['analysis', gameId] as const,
  orders: (marketId?: string) => ['orders', marketId ?? 'all'] as const,
  tradeHistory: ['tradeHistory'] as const,
  pregameDates: ['pregameDates'] as const,
  pregameOrders: (date: string) => ['pregameOrders', date] as const,
}

// ---------------------------------------------------------------------------
// Portfolio
// ---------------------------------------------------------------------------

export function usePortfolio() {
  return useQuery({
    queryKey: queryKeys.portfolio,
    queryFn: () => fetchApi<PortfolioResponse>('/portfolio'),
    refetchInterval: 30_000,
    staleTime: 30_000,
  })
}

export function usePositions() {
  return useQuery({
    queryKey: queryKeys.positions,
    queryFn: () => fetchApi<PositionsResponse>('/positions'),
    refetchInterval: 30_000,
    staleTime: 30_000,
  })
}

// ---------------------------------------------------------------------------
// Markets
// ---------------------------------------------------------------------------

export function useGames(date?: string) {
  return useQuery({
    queryKey: queryKeys.games(date),
    queryFn: () => {
      const qs = date ? `?date=${date}` : ''
      return fetchApi<GameSummary[]>(`/games${qs}`)
    },
    staleTime: 60_000,
  })
}

export function useMarkets(date?: string) {
  return useQuery({
    queryKey: queryKeys.markets(date),
    queryFn: () => {
      const qs = date ? `?date=${date}` : ''
      return fetchApi<GameMarketSummary[]>(`/markets${qs}`)
    },
    refetchInterval: 30_000,
    staleTime: 30_000,
  })
}

// ---------------------------------------------------------------------------
// Analysis
// ---------------------------------------------------------------------------

export function useAnalysis(gameId: string) {
  return useQuery({
    queryKey: queryKeys.analysis(gameId),
    queryFn: () => fetchApi<GameAdvisoryResponse>(`/analysis/${gameId}`),
    retry: (failureCount, error) => {
      // Don't retry 404s — analysis just hasn't been run yet
      if (error instanceof ApiError && error.status === 404) return false
      return failureCount < 2
    },
    staleTime: Infinity,
  })
}

export function useRunAnalysis() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ gameId, withAi = true, force = false }: { gameId: string; withAi?: boolean; force?: boolean }) => {
      const params = new URLSearchParams({ with_ai: String(withAi) })
      if (force) params.set('force', 'true')
      return postJson<GameAdvisoryResponse>(
        `/analysis/${gameId}/run?${params}`,
        {},
      )
    },
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.analysis(data.game.game_id), data)
      // Invalidate markets so cached_verdict updates
      void qc.invalidateQueries({ queryKey: ['markets'] })
    },
    onError: (error) => toast.error(`Analysis failed: ${error.message}`),
  })
}

export function useRunAllAnalysis() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ withAi = true, date, force = false }: { withAi?: boolean; date?: string; force?: boolean } = {}) => {
      const params = new URLSearchParams({ with_ai: String(withAi) })
      if (date) params.set('date', date)
      if (force) params.set('force', 'true')
      return postJson<GameAdvisoryResponse[]>(`/analysis/run-all?${params}`, {})
    },
    onSuccess: (data) => {
      for (const advisory of data) {
        qc.setQueryData(queryKeys.analysis(advisory.game.game_id), advisory)
      }
      void qc.invalidateQueries({ queryKey: ['markets'] })
    },
    onError: (error) => toast.error(`Analysis failed: ${error.message}`),
  })
}

// ---------------------------------------------------------------------------
// Orders
// ---------------------------------------------------------------------------

export function useOrders(marketId?: string) {
  return useQuery({
    queryKey: queryKeys.orders(marketId),
    queryFn: () => {
      const qs = marketId ? `?market_id=${marketId}` : ''
      return fetchApi<OrderSchema[]>(`/trading/orders${qs}`)
    },
    refetchInterval: 15_000,
  })
}

export function usePlaceOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: OrderRequest) => postJson<OrderResponse>('/trading/order', req),
    onSuccess: (data) => {
      void qc.invalidateQueries({ queryKey: ['orders'] })
      void qc.invalidateQueries({ queryKey: queryKeys.portfolio })
      void qc.invalidateQueries({ queryKey: queryKeys.positions })
      if (data.success) toast.success('Order placed')
    },
    onError: (error) => toast.error(`Failed to place order: ${error.message}`),
  })
}

export function useCancelOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (orderId: string) => deleteApi<OrderResponse>(`/trading/order/${orderId}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['orders'] })
      void qc.invalidateQueries({ queryKey: queryKeys.portfolio })
      toast.success('Order cancelled')
    },
    onError: (error) => toast.error(`Failed to cancel order: ${error.message}`),
  })
}

// ---------------------------------------------------------------------------
// Trade History
// ---------------------------------------------------------------------------

export function useTradeHistory() {
  return useQuery({
    queryKey: queryKeys.tradeHistory,
    queryFn: () => fetchApi<TradeHistoryResponse>('/trading/history'),
    refetchInterval: 60_000,
    staleTime: 60_000,
  })
}

// ---------------------------------------------------------------------------
// Pregame Orders
// ---------------------------------------------------------------------------

export function usePregameDates() {
  return useQuery({
    queryKey: queryKeys.pregameDates,
    queryFn: () => fetchApi<PregameDatesResponse>('/pregame-orders/dates'),
    staleTime: 5 * 60_000,
  })
}

export function usePregameOrders(date: string) {
  return useQuery({
    queryKey: queryKeys.pregameOrders(date),
    queryFn: () => fetchApi<PregameOrdersResponse>(`/pregame-orders?date=${date}`),
    enabled: !!date,
    refetchInterval: 30_000,
    staleTime: 30_000,
  })
}

export function useCheckFills() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (date: string) =>
      postJson<PregameOrdersResponse>(`/pregame-orders/check-fills?date=${date}`, {}),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.pregameOrders(data.date), data)
      toast.success('Fills checked')
    },
    onError: (error) => toast.error(`Failed to check fills: ${error.message}`),
  })
}

export function useRecordPregameOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: RecordPregameOrderRequest) =>
      postJson<PregameOrder>('/pregame-orders/record', req),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.pregameDates })
      void qc.invalidateQueries({ queryKey: ['pregameOrders'] })
    },
  })
}

export function usePlaceSell() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ orderId, date }: { orderId: string; date: string }) =>
      postJson<PregameOrder>(`/pregame-orders/${encodeURIComponent(orderId)}/place-sell?date=${date}`, {}),
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({ queryKey: queryKeys.pregameOrders(variables.date) })
      void qc.invalidateQueries({ queryKey: queryKeys.portfolio })
      toast.success('Sell order placed')
    },
    onError: (error) => toast.error(`Failed to place sell: ${error.message}`),
  })
}
