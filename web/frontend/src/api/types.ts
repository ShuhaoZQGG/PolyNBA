// ---------------------------------------------------------------------------
// Game / Market types
// ---------------------------------------------------------------------------

export interface GameSummary {
  game_id: string
  status: string
  home_team_id: string
  home_team_name: string
  home_team_abbreviation: string
  home_score: number
  away_team_id: string
  away_team_name: string
  away_team_abbreviation: string
  away_score: number
  game_date: string | null
  broadcast: string | null
}

export interface PolymarketMarket {
  condition_id: string
  question: string
  home_token_id: string
  away_token_id: string
  home_team_name: string
  away_team_name: string
  liquidity: number
  volume: number
  home_price: number | null
  away_price: number | null
  is_tradeable: boolean
  end_date: string | null
}

export interface MarketPrices {
  condition_id: string
  home_mid_price: number
  away_mid_price: number
  home_best_bid: number | null
  home_best_ask: number | null
  away_best_bid: number | null
  away_best_ask: number | null
  home_bid_depth: number
  home_ask_depth: number
  away_bid_depth: number
  away_ask_depth: number
  home_spread: number | null
  away_spread: number | null
  fetched_at: string
}

export interface PreGameEstimate {
  home_team_abbr: string
  away_team_abbr: string
  raw_model_prob: number
  h2h_adjustment: number
  model_prob: number
  market_prob: number
  blended_prob: number
  edge: number
  edge_percent: number
  kelly_fraction: number
  suggested_bet_usdc: number
  confidence: number
  verdict: string
  bet_side: string
  factors_summary: string[]
}

export interface TradingPlan {
  strategy: string
  entry_price: number
  exit_price: number | null
  expected_roi: number
  bet_side_prob: number
  spread: number | null
  spread_pct: number | null
  depth_available: number
  liquidity_warning: boolean
}

export interface MatchupInsight {
  category: string
  description: string
  advantage: 'home' | 'away' | 'even'
}

export interface InjuryImpact {
  team: string
  severity: 'critical' | 'significant' | 'minor' | 'none'
  description: string
}

export interface PregameAIAnalysis {
  headline: string
  narrative: string
  verdict_rationale: string
  matchup_insights: MatchupInsight[]
  injury_impact: InjuryImpact[]
  key_factors_for: string[]
  key_factors_against: string[]
  confidence_rating: number
  market_efficiency: 'inefficient' | 'fair' | 'efficient'
  upset_risk: 'very_low' | 'low' | 'moderate' | 'high'
  game_script: string
}

export interface TeamStats {
  team_id: string
  team_name: string
  team_abbreviation: string
  wins: number
  losses: number
  win_percentage: number
  home_wins: number
  home_losses: number
  away_wins: number
  away_losses: number
  net_rating: number
  offensive_rating: number
  defensive_rating: number
  pace: number
  points_per_game: number
  points_allowed_per_game: number
  current_streak: number
  last_10_wins: number
  last_10_losses: number
  clutch_net_rating: number
}

export interface PlayerInjury {
  player_id: string
  player_name: string
  team_id: string
  status: string
  injury_description: string
  is_out: boolean
  is_questionable: boolean
  points_per_game: number | null
  rebounds_per_game: number | null
  assists_per_game: number | null
  minutes_per_game: number | null
}

export interface TeamContext {
  stats: TeamStats
  injuries: PlayerInjury[]
  key_players_out: PlayerInjury[]
  has_significant_injuries: boolean
}

export interface HeadToHead {
  team1_id: string
  team2_id: string
  team1_wins: number
  team2_wins: number
  games_played: number
  team1_win_percentage: number
  team1_avg_margin: number
}

export interface GameAdvisoryResponse {
  game: GameSummary
  market: PolymarketMarket
  prices: MarketPrices
  estimate: PreGameEstimate
  trading_plan: TradingPlan | null
  ai_analysis: string | null
  ai_detail: PregameAIAnalysis | null
  home_context: TeamContext | null
  away_context: TeamContext | null
  head_to_head: HeadToHead | null
  analyzed_at: string | null
}

export interface GameMarketSummary {
  game: GameSummary
  market: PolymarketMarket
  prices: MarketPrices | null
  cached_verdict: string | null
  cached_estimate: PreGameEstimate | null
}

export type GamesResponse = GameSummary[]

// ---------------------------------------------------------------------------
// Portfolio types
// ---------------------------------------------------------------------------

export interface Balance {
  usdc: number
  locked_usdc: number
  available_usdc: number
}

export interface OrderSchema {
  order_id: string
  market_id: string
  token_id: string
  side: string
  size: number
  price: number
  status: string
  filled_size: number
  avg_fill_price: number
  created_at: string
  updated_at: string
  strategy_id: string | null
}

export interface PortfolioResponse {
  balance: Balance
  positions: Record<string, number>
  open_orders: OrderSchema[]
  is_live_mode: boolean
}

// ---------------------------------------------------------------------------
// Trading types
// ---------------------------------------------------------------------------

export interface OrderRequest {
  market_id: string
  token_id: string
  side: 'buy' | 'sell'
  size_usdc: number
  price: number
  strategy_id?: string
}

export interface OrderResponse {
  success: boolean
  order: OrderSchema | null
  error: string | null
}

// ---------------------------------------------------------------------------
// Trade history types
// ---------------------------------------------------------------------------

export interface TradeHistoryEntry {
  activity: string // "Bought", "Sold", "Lost", "Won"
  market_name: string
  outcome: string
  price: number
  shares: number
  value: number // negative = spent, positive = received
  timestamp: string // ISO datetime
  condition_id: string
  asset_id: string
  side: string // "BUY" or "SELL"
  trader_side: string // "MAKER" or "TAKER"
}

export interface TradeHistoryResponse {
  entries: TradeHistoryEntry[]
  total_pnl: number
  total_fees: number
}

// ---------------------------------------------------------------------------
// Positions types
// ---------------------------------------------------------------------------

export interface Position {
  token_id: string
  condition_id: string
  market_name: string
  outcome: string
  shares: number         // net shares held
  avg_price: number      // average buy price (0-1)
  current_price: number  // mid price from order book
  cost: number           // total USDC spent buying
  to_win: number         // payout if outcome resolves YES ($1 per share)
  current_value: number  // shares * current_price
  pnl: number            // unrealized P&L in USDC
  pnl_percent: number    // pnl / cost * 100
}

export interface PositionsResponse {
  positions: Position[]
  total_value: number
  total_cost: number
  total_pnl: number
  total_pnl_percent: number
}

// ---------------------------------------------------------------------------
// Pregame order tracking types
// ---------------------------------------------------------------------------

export interface PregameOrder {
  order_id: string
  game: string
  team: string
  token_id: string
  market_id: string
  side: string
  shares: number
  entry_price: number
  strategy: string
  exit_price: number | null
  status: string
  filled_shares: number
  sell_order_id: string | null
  needs_sell: boolean
}

export interface PregameOrdersSummary {
  total: number
  open: number
  matched: number
  sell_placed: number
  needs_sell: number
  total_cost: number
}

export interface PregameOrdersResponse {
  date: string
  created_at: string | null
  updated_at: string | null
  orders: PregameOrder[]
  summary: PregameOrdersSummary
}

export interface RecordPregameOrderRequest {
  order_id: string
  game: string
  team: string
  token_id: string
  market_id: string
  side: string
  shares: number
  entry_price: number
  strategy: string
  exit_price: number | null
  date?: string
}

export interface PregameDatesResponse {
  dates: string[]
}

// ---------------------------------------------------------------------------
// Team Data types
// ---------------------------------------------------------------------------

export interface TeamInjuries {
  team_id: string
  team_abbreviation: string
  injuries: PlayerInjury[]
  key_players_out: number
}

export interface PlayerStatsEntry {
  player_name: string
  team_abbreviation: string
  games_played: number
  minutes_per_game: number
  points_per_game: number
  rebounds_per_game: number
  assists_per_game: number
  steals_per_game: number
  blocks_per_game: number
  field_goal_pct: number
  three_point_pct: number
  free_throw_pct: number
  true_shooting_pct: number | null
  usage_rate: number | null
  net_rating: number | null
}

export interface RefreshResponse {
  refreshed: string[]
  message: string
}
