# PolyNBA Web Frontend

React + TypeScript single-page application for the PolyNBA betting advisor dashboard.

## Tech Stack

- **Vite** — Build tool and dev server
- **React 18** — UI framework
- **TypeScript** — Type-safe JavaScript
- **TanStack Query** — Server state management and data fetching
- **Zustand** — Client state management
- **Recharts** — Charts and data visualization
- **Tailwind CSS v4** — Utility-first styling
- **React Router** — Client-side routing

## Pages

- **Dashboard** (`/`) — Game grid with today's NBA matchups, market prices, and probability analysis
- **Game Detail** (`/game/:id`) — Deep dive into a single game with analysis factors, order form, and positions
- **Activity** (`/activity`) — Trade history, open orders, and P&L chart

## Running

```bash
# Install dependencies
npm install

# Start dev server (http://localhost:5173)
npm run dev
```

## Building

```bash
npm run build
```

Output goes to `dist/` (gitignored).

## Project Structure

```
src/
  api/          # API client, TanStack Query hooks, types
  components/   # Reusable UI components
    analysis/   # Probability bars, factor lists, suggestions
    common/     # Card, Badge, DataTable, StatCard, LoadingSkeleton
    games/      # GameCard, GameGrid, OddsPill, TeamBadge
    layout/     # AppShell, TopBar
    portfolio/  # BalanceCard, PnLChart, PositionsList, SellModal
    pregame/    # PregameOrdersTab
    trading/    # OrderForm, OrderConfirmation, OrdersTable
  constants/    # Team colors and metadata
  pages/        # Dashboard, GameDetail, Activity
  store/        # Zustand store
```
