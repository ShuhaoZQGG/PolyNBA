import { create } from 'zustand'

interface OrderFormState {
  selectedTeam: 'home' | 'away'
  orderSide: 'BUY' | 'SELL'
  orderShares: number
  orderPrice: number
  showConfirmation: boolean
}

interface OrderFormActions {
  setSelectedTeam: (team: 'home' | 'away') => void
  setOrderSide: (side: 'BUY' | 'SELL') => void
  setOrderShares: (shares: number) => void
  setOrderPrice: (price: number) => void
  addToShares: (delta: number) => void
  setShowConfirmation: (show: boolean) => void
  resetForm: () => void
}

const defaultState: OrderFormState = {
  selectedTeam: 'home',
  orderSide: 'BUY',
  orderShares: 0,
  orderPrice: 0,
  showConfirmation: false,
}

const useStore = create<OrderFormState & OrderFormActions>((set) => ({
  ...defaultState,

  setSelectedTeam: (team) => set({ selectedTeam: team }),
  setOrderSide: (side) => set({ orderSide: side }),
  setOrderShares: (shares) => set({ orderShares: Math.max(0, shares) }),
  setOrderPrice: (price) => set({ orderPrice: Math.max(0, Math.min(0.99, price)) }),
  addToShares: (delta) =>
    set((state) => ({ orderShares: Math.max(0, state.orderShares + delta) })),
  setShowConfirmation: (show) => set({ showConfirmation: show }),
  resetForm: () => set(defaultState),
}))

export default useStore
