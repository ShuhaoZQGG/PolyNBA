import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppShell from './components/layout/AppShell'
import Dashboard from './pages/Dashboard'
import GameDetail from './pages/GameDetail'
import Activity from './pages/Activity'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/markets" replace />} />
          <Route path="/markets" element={<Dashboard />} />
          <Route path="/game/:id" element={<GameDetail />} />
          <Route path="/activity" element={<Activity />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
