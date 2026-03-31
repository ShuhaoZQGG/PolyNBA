"""Pydantic v2 response schemas for the PolyNBA FastAPI backend.

All dataclass-to-schema conversions are done via explicit ``from_*`` class
methods rather than ``model_validate`` so we stay in full control of field
mapping and can safely serialise Decimal → float and datetime → ISO string.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dec(v: Optional[Decimal]) -> Optional[float]:
    return float(v) if v is not None else None


def _dec_req(v: Decimal) -> float:
    return float(v)


def _dt(v: Optional[datetime]) -> Optional[str]:
    return v.isoformat() if v is not None else None


# ---------------------------------------------------------------------------
# Market / Price schemas
# ---------------------------------------------------------------------------


class MarketPricesSchema(BaseModel):
    condition_id: str
    home_mid_price: float
    away_mid_price: float
    home_best_bid: Optional[float] = None
    home_best_ask: Optional[float] = None
    away_best_bid: Optional[float] = None
    away_best_ask: Optional[float] = None
    home_bid_depth: float
    home_ask_depth: float
    away_bid_depth: float
    away_ask_depth: float
    home_spread: Optional[float] = None
    away_spread: Optional[float] = None
    fetched_at: str

    @classmethod
    def from_dataclass(cls, mp) -> "MarketPricesSchema":
        return cls(
            condition_id=mp.condition_id,
            home_mid_price=_dec_req(mp.home_mid_price),
            away_mid_price=_dec_req(mp.away_mid_price),
            home_best_bid=_dec(mp.home_best_bid),
            home_best_ask=_dec(mp.home_best_ask),
            away_best_bid=_dec(mp.away_best_bid),
            away_best_ask=_dec(mp.away_best_ask),
            home_bid_depth=_dec_req(mp.home_bid_depth),
            home_ask_depth=_dec_req(mp.home_ask_depth),
            away_bid_depth=_dec_req(mp.away_bid_depth),
            away_ask_depth=_dec_req(mp.away_ask_depth),
            home_spread=_dec(mp.home_spread),
            away_spread=_dec(mp.away_spread),
            fetched_at=mp.fetched_at.isoformat(),
        )


class PolymarketMarketSchema(BaseModel):
    condition_id: str
    question: str
    home_token_id: str
    away_token_id: str
    home_team_name: str
    away_team_name: str
    liquidity: float
    volume: float
    home_price: Optional[float] = None
    away_price: Optional[float] = None
    is_tradeable: bool
    end_date: Optional[str] = None

    @classmethod
    def from_dataclass(cls, m) -> "PolymarketMarketSchema":
        return cls(
            condition_id=m.condition_id,
            question=m.question,
            home_token_id=m.home_token_id,
            away_token_id=m.away_token_id,
            home_team_name=m.home_team_name,
            away_team_name=m.away_team_name,
            liquidity=float(m.liquidity),
            volume=float(m.volume),
            home_price=_dec(m.home_price),
            away_price=_dec(m.away_price),
            is_tradeable=m.is_tradeable,
            end_date=_dt(m.end_date),
        )


# ---------------------------------------------------------------------------
# Game schemas
# ---------------------------------------------------------------------------


class GameSummarySchema(BaseModel):
    game_id: str
    status: str
    home_team_id: str
    home_team_name: str
    home_team_abbreviation: str
    home_score: int
    away_team_id: str
    away_team_name: str
    away_team_abbreviation: str
    away_score: int
    game_date: Optional[str] = None
    broadcast: Optional[str] = None

    @classmethod
    def from_dataclass(cls, g) -> "GameSummarySchema":
        return cls(
            game_id=g.game_id,
            status=g.status.value if hasattr(g.status, "value") else str(g.status),
            home_team_id=g.home_team_id,
            home_team_name=g.home_team_name,
            home_team_abbreviation=g.home_team_abbreviation,
            home_score=g.home_score,
            away_team_id=g.away_team_id,
            away_team_name=g.away_team_name,
            away_team_abbreviation=g.away_team_abbreviation,
            away_score=g.away_score,
            game_date=_dt(g.game_date),
            broadcast=g.broadcast,
        )


# ---------------------------------------------------------------------------
# Team context / H2H schemas
# ---------------------------------------------------------------------------


class TeamStatsSchema(BaseModel):
    team_id: str
    team_name: str
    team_abbreviation: str
    wins: int
    losses: int
    win_percentage: float
    home_wins: int
    home_losses: int
    away_wins: int
    away_losses: int
    net_rating: float
    offensive_rating: float
    defensive_rating: float
    pace: float
    points_per_game: float
    points_allowed_per_game: float
    current_streak: int
    last_10_wins: int
    last_10_losses: int
    clutch_net_rating: float

    @classmethod
    def from_dataclass(cls, ts) -> "TeamStatsSchema":
        return cls(
            team_id=ts.team_id,
            team_name=ts.team_name,
            team_abbreviation=ts.team_abbreviation,
            wins=ts.wins,
            losses=ts.losses,
            win_percentage=ts.win_percentage,
            home_wins=ts.home_wins,
            home_losses=ts.home_losses,
            away_wins=ts.away_wins,
            away_losses=ts.away_losses,
            net_rating=ts.net_rating,
            offensive_rating=ts.offensive_rating,
            defensive_rating=ts.defensive_rating,
            pace=ts.pace,
            points_per_game=ts.points_per_game,
            points_allowed_per_game=ts.points_allowed_per_game,
            current_streak=ts.current_streak,
            last_10_wins=ts.last_10_wins,
            last_10_losses=ts.last_10_losses,
            clutch_net_rating=ts.clutch_net_rating,
        )


class PlayerInjurySchema(BaseModel):
    player_id: str
    player_name: str
    team_id: str
    status: str
    injury_description: str
    is_out: bool
    is_questionable: bool
    points_per_game: Optional[float] = None
    rebounds_per_game: Optional[float] = None
    assists_per_game: Optional[float] = None
    minutes_per_game: Optional[float] = None

    @classmethod
    def from_dataclass(cls, inj) -> "PlayerInjurySchema":
        ps = inj.player_stats
        return cls(
            player_id=inj.player_id,
            player_name=inj.player_name,
            team_id=inj.team_id,
            status=inj.status,
            injury_description=inj.injury_description,
            is_out=inj.is_out,
            is_questionable=inj.is_questionable,
            points_per_game=ps.points_per_game if ps else None,
            rebounds_per_game=ps.rebounds_per_game if ps else None,
            assists_per_game=ps.assists_per_game if ps else None,
            minutes_per_game=ps.minutes_per_game if ps else None,
        )


class HeadToHeadSchema(BaseModel):
    team1_id: str
    team2_id: str
    team1_wins: int
    team2_wins: int
    games_played: int
    team1_win_percentage: float
    team1_avg_margin: float

    @classmethod
    def from_dataclass(cls, h2h) -> "HeadToHeadSchema":
        return cls(
            team1_id=h2h.team1_id,
            team2_id=h2h.team2_id,
            team1_wins=h2h.team1_wins,
            team2_wins=h2h.team2_wins,
            games_played=h2h.games_played,
            team1_win_percentage=h2h.team1_win_percentage,
            team1_avg_margin=h2h.team1_avg_margin,
        )


class TeamContextSchema(BaseModel):
    stats: TeamStatsSchema
    injuries: list[PlayerInjurySchema]
    key_players_out: list[PlayerInjurySchema]
    has_significant_injuries: bool

    @classmethod
    def from_dataclass(cls, ctx) -> "TeamContextSchema":
        return cls(
            stats=TeamStatsSchema.from_dataclass(ctx.stats),
            injuries=[PlayerInjurySchema.from_dataclass(i) for i in ctx.injuries],
            key_players_out=[PlayerInjurySchema.from_dataclass(i) for i in ctx.key_players_out],
            has_significant_injuries=ctx.has_significant_injuries,
        )


class GameContextResponse(BaseModel):
    game_id: str
    home_context: Optional[TeamContextSchema] = None
    away_context: Optional[TeamContextSchema] = None
    head_to_head: Optional[HeadToHeadSchema] = None


# ---------------------------------------------------------------------------
# Advisory / Analysis schemas
# ---------------------------------------------------------------------------


class PreGameEstimateSchema(BaseModel):
    home_team_abbr: str
    away_team_abbr: str
    raw_model_prob: float
    h2h_adjustment: float
    model_prob: float
    market_prob: float
    blended_prob: float
    edge: float
    edge_percent: float
    kelly_fraction: float
    suggested_bet_usdc: float
    confidence: int
    verdict: str
    bet_side: str
    factors_summary: list[str]

    @classmethod
    def from_dataclass(cls, est) -> "PreGameEstimateSchema":
        return cls(
            home_team_abbr=est.home_team_abbr,
            away_team_abbr=est.away_team_abbr,
            raw_model_prob=est.raw_model_prob,
            h2h_adjustment=est.h2h_adjustment,
            model_prob=est.model_prob,
            market_prob=est.market_prob,
            blended_prob=est.blended_prob,
            edge=est.edge,
            edge_percent=est.edge_percent,
            kelly_fraction=est.kelly_fraction,
            suggested_bet_usdc=est.suggested_bet_usdc,
            confidence=est.confidence,
            verdict=est.verdict,
            bet_side=est.bet_side,
            factors_summary=est.factors_summary,
        )


class TradingPlanSchema(BaseModel):
    strategy: str
    entry_price: float
    exit_price: Optional[float] = None
    expected_roi: float
    bet_side_prob: float
    spread: Optional[float] = None
    spread_pct: Optional[float] = None
    depth_available: float
    liquidity_warning: bool

    @classmethod
    def from_dataclass(cls, tp) -> "TradingPlanSchema":
        return cls(
            strategy=tp.strategy,
            entry_price=tp.entry_price,
            exit_price=tp.exit_price,
            expected_roi=tp.expected_roi,
            bet_side_prob=tp.bet_side_prob,
            spread=tp.spread,
            spread_pct=tp.spread_pct,
            depth_available=tp.depth_available,
            liquidity_warning=tp.liquidity_warning,
        )


class MatchupInsightSchema(BaseModel):
    category: str
    description: str
    advantage: Literal["home", "away", "even"]


class InjuryImpactSchema(BaseModel):
    team: str
    severity: Literal["critical", "significant", "minor", "none"]
    description: str


class PregameAIAnalysisSchema(BaseModel):
    headline: str
    narrative: str
    verdict_rationale: str
    matchup_insights: list[MatchupInsightSchema]
    injury_impact: list[InjuryImpactSchema]
    key_factors_for: list[str]
    key_factors_against: list[str]
    confidence_rating: int
    market_efficiency: Literal["inefficient", "fair", "efficient"]
    upset_risk: Literal["very_low", "low", "moderate", "high"]
    game_script: str

    @classmethod
    def from_pydantic(cls, ai) -> "PregameAIAnalysisSchema":
        return cls(
            headline=ai.headline,
            narrative=ai.narrative,
            verdict_rationale=ai.verdict_rationale,
            matchup_insights=[
                MatchupInsightSchema(
                    category=m.category,
                    description=m.description,
                    advantage=m.advantage,
                )
                for m in ai.matchup_insights
            ],
            injury_impact=[
                InjuryImpactSchema(
                    team=i.team,
                    severity=i.severity,
                    description=i.description,
                )
                for i in ai.injury_impact
            ],
            key_factors_for=ai.key_factors_for,
            key_factors_against=ai.key_factors_against,
            confidence_rating=ai.confidence_rating,
            market_efficiency=ai.market_efficiency,
            upset_risk=ai.upset_risk,
            game_script=ai.game_script,
        )


class GameAdvisoryResponse(BaseModel):
    """Full advisory for a single pre-game matchup."""

    game: GameSummarySchema
    market: PolymarketMarketSchema
    prices: MarketPricesSchema
    estimate: PreGameEstimateSchema
    trading_plan: Optional[TradingPlanSchema] = None
    ai_analysis: Optional[str] = None
    ai_detail: Optional[PregameAIAnalysisSchema] = None
    home_context: Optional[TeamContextSchema] = None
    away_context: Optional[TeamContextSchema] = None
    head_to_head: Optional[HeadToHeadSchema] = None
    analyzed_at: Optional[str] = None  # ISO timestamp of when AI analysis was cached

    @classmethod
    def from_advisory(cls, adv, analyzed_at: Optional[datetime] = None) -> "GameAdvisoryResponse":
        return cls(
            game=GameSummarySchema.from_dataclass(adv.game),
            market=PolymarketMarketSchema.from_dataclass(adv.market),
            prices=MarketPricesSchema.from_dataclass(adv.prices),
            estimate=PreGameEstimateSchema.from_dataclass(adv.estimate),
            trading_plan=TradingPlanSchema.from_dataclass(adv.trading_plan) if adv.trading_plan else None,
            ai_analysis=adv.ai_analysis,
            ai_detail=PregameAIAnalysisSchema.from_pydantic(adv.ai_detail) if adv.ai_detail else None,
            home_context=TeamContextSchema.from_dataclass(adv.home_context) if adv.home_context else None,
            away_context=TeamContextSchema.from_dataclass(adv.away_context) if adv.away_context else None,
            head_to_head=HeadToHeadSchema.from_dataclass(adv.head_to_head) if adv.head_to_head else None,
            analyzed_at=analyzed_at.isoformat() if analyzed_at else None,
        )


# ---------------------------------------------------------------------------
# Markets list schema (lightweight — no full analysis)
# ---------------------------------------------------------------------------


class GameMarketSummary(BaseModel):
    """Combined game + market + prices for the markets list endpoint."""

    game: GameSummarySchema
    market: PolymarketMarketSchema
    prices: Optional[MarketPricesSchema] = None
    # If analysis has already been cached, surface the headline verdict.
    cached_verdict: Optional[str] = None
    cached_estimate: Optional[PreGameEstimateSchema] = None


# ---------------------------------------------------------------------------
# Portfolio schemas
# ---------------------------------------------------------------------------


class BalanceSchema(BaseModel):
    usdc: float
    locked_usdc: float
    available_usdc: float

    @classmethod
    def from_dataclass(cls, bal) -> "BalanceSchema":
        return cls(
            usdc=float(bal.usdc),
            locked_usdc=float(bal.locked_usdc),
            available_usdc=float(bal.available_usdc),
        )


class OrderSchema(BaseModel):
    order_id: str
    market_id: str
    token_id: str
    side: str
    size: float
    price: float
    status: str
    filled_size: float
    avg_fill_price: float
    created_at: str
    updated_at: str
    strategy_id: Optional[str] = None

    @classmethod
    def from_dataclass(cls, order) -> "OrderSchema":
        return cls(
            order_id=order.order_id,
            market_id=order.market_id,
            token_id=order.token_id,
            side=order.side.value if hasattr(order.side, "value") else str(order.side),
            size=float(order.size),
            price=float(order.price),
            status=order.status.value if hasattr(order.status, "value") else str(order.status),
            filled_size=float(order.filled_size),
            avg_fill_price=float(order.avg_fill_price),
            created_at=order.created_at.isoformat(),
            updated_at=order.updated_at.isoformat(),
            strategy_id=order.strategy_id,
        )


class PortfolioResponse(BaseModel):
    balance: BalanceSchema
    positions: dict[str, float]
    open_orders: list[OrderSchema]
    is_live_mode: bool


# ---------------------------------------------------------------------------
# Trading request / response schemas
# ---------------------------------------------------------------------------


class OrderRequest(BaseModel):
    """Request body for placing a new order."""

    market_id: str = Field(description="Polymarket condition ID")
    token_id: str = Field(description="Token ID for the outcome to buy/sell")
    side: Literal["buy", "sell"] = Field(description="Order side")
    size_usdc: float = Field(gt=0, description="Order size in USDC (converted to shares internally)")
    price: float = Field(gt=0, lt=1, description="Limit price per share (0–1)")
    strategy_id: Optional[str] = Field(default=None, description="Optional strategy tag")


class OrderResponse(BaseModel):
    success: bool
    order: Optional[OrderSchema] = None
    error: Optional[str] = None

    @classmethod
    def from_result(cls, result) -> "OrderResponse":
        return cls(
            success=result.success,
            order=OrderSchema.from_dataclass(result.order) if result.order else None,
            error=result.error,
        )


# ---------------------------------------------------------------------------
# Trade history schemas
# ---------------------------------------------------------------------------


class TradeHistoryEntrySchema(BaseModel):
    """Single trade activity entry (matches Polymarket History tab)."""

    activity: str  # "Bought", "Sold", "Lost", "Won"
    market_name: str  # "Pistons vs. Nets"
    outcome: str  # "Pistons"
    price: float  # Entry price (e.g. 0.90)
    shares: float  # Number of shares
    value: float  # Total cost/revenue (negative=spent, positive=received)
    timestamp: str  # ISO datetime
    condition_id: str  # For linking to game detail
    asset_id: str  # Token ID
    side: str  # "BUY" or "SELL"
    trader_side: str  # "MAKER" or "TAKER"


class TradeHistoryResponse(BaseModel):
    entries: list[TradeHistoryEntrySchema]
    total_pnl: float
    total_fees: float


# ---------------------------------------------------------------------------
# Positions schemas
# ---------------------------------------------------------------------------


class PositionSchema(BaseModel):
    token_id: str
    condition_id: str
    market_name: str
    outcome: str
    shares: float         # net_shares held
    avg_price: float      # average buy price (0-1)
    current_price: float  # mid price from order book
    cost: float           # total USDC spent buying
    to_win: float         # payout if outcome resolves YES ($1 per share)
    current_value: float  # shares * current_price
    pnl: float            # unrealized P&L in USDC
    pnl_percent: float    # pnl / cost * 100


class PositionsResponse(BaseModel):
    positions: list[PositionSchema]
    total_value: float
    total_cost: float
    total_pnl: float
    total_pnl_percent: float


# ---------------------------------------------------------------------------
# Pregame order tracking schemas
# ---------------------------------------------------------------------------


class PregameOrderSchema(BaseModel):
    order_id: str
    game: str
    team: str
    token_id: str
    market_id: str
    side: str
    shares: int
    entry_price: float
    strategy: str
    exit_price: Optional[float] = None
    status: str
    filled_shares: int
    sell_order_id: Optional[str] = None
    needs_sell: bool

    @classmethod
    def from_ledger_entry(cls, entry: dict) -> "PregameOrderSchema":
        status = entry.get("status", "OPEN")
        strategy = entry.get("strategy", "")
        exit_price = entry.get("exit_price")
        sell_order_id = entry.get("sell_order_id")
        filled = entry.get("filled_shares", 0)

        needs_sell = (
            status == "MATCHED"
            and strategy == "TRADE"
            and exit_price is not None
            and not sell_order_id
            and filled > 0
        )

        return cls(
            order_id=entry["order_id"],
            game=entry["game"],
            team=entry["team"],
            token_id=entry["token_id"],
            market_id=entry["market_id"],
            side=entry.get("side", "buy"),
            shares=entry.get("shares", 0),
            entry_price=entry["entry_price"],
            strategy=strategy,
            exit_price=exit_price,
            status=status,
            filled_shares=filled,
            sell_order_id=sell_order_id,
            needs_sell=needs_sell,
        )


class PregameOrdersSummary(BaseModel):
    total: int
    open: int
    matched: int
    sell_placed: int
    needs_sell: int
    total_cost: float


class PregameOrdersResponse(BaseModel):
    date: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    orders: list[PregameOrderSchema]
    summary: PregameOrdersSummary


class RecordPregameOrderRequest(BaseModel):
    """Request body for recording a new pregame order in the ledger."""

    order_id: str
    game: str  # "WSH @ MIA"
    team: str  # "WSH"
    token_id: str
    market_id: str
    side: str = "buy"
    shares: float
    entry_price: float
    strategy: str  # "TRADE" or "RESOLUTION"
    exit_price: Optional[float] = None
    date: Optional[str] = None  # YYYYMMDD, defaults to today


class UpdateExitPriceRequest(BaseModel):
    """Request body for updating an order's exit price."""

    exit_price: Optional[float] = None


class PregameDatesResponse(BaseModel):
    dates: list[str]


# ---------------------------------------------------------------------------
# Data router schemas (injuries, team strength, player stats, refresh)
# ---------------------------------------------------------------------------


class TeamInjuriesSchema(BaseModel):
    """Injury summary for a single team."""

    team_id: str
    team_abbreviation: str
    injuries: list[PlayerInjurySchema]
    key_players_out: int


class PlayerStatsEntry(BaseModel):
    """Per-player season average stats returned by the player-stats endpoint."""

    player_name: str
    team_abbreviation: str
    games_played: int
    minutes_per_game: float
    points_per_game: float
    rebounds_per_game: float
    assists_per_game: float
    steals_per_game: float
    blocks_per_game: float
    field_goal_pct: float
    three_point_pct: float
    free_throw_pct: float
    # Advanced stats — None when not yet fetched from NBA.com
    true_shooting_pct: Optional[float] = None
    usage_rate: Optional[float] = None
    net_rating: Optional[float] = None


class RefreshRequest(BaseModel):
    """Request body for the /api/data/refresh endpoint."""

    targets: list[Literal["injuries", "team_stats", "player_stats", "all"]]


class RefreshResponse(BaseModel):
    """Response returned after a successful cache refresh."""

    refreshed: list[str]
    message: str
