import { Route, Routes } from 'react-router-dom'

import TopNav from './components/TopNav'
import DashboardPage from './pages/DashboardPage'
import TopicsPage from './pages/TopicsPage'
import QuizPage from './pages/QuizPage'
import PlannerPage from './pages/PlannerPage'

const DEMO_SESSION = Object.freeze({
  user_id: 'local-demo-user',
  email: 'Demo mode (no login)',
})

export default function App() {
  const userId = DEMO_SESSION.user_id

  return (
    <div className="app-shell">
      <TopNav userEmail={DEMO_SESSION.email} />
      <main className="content-shell">
        <Routes>
          <Route path="/" element={<DashboardPage userId={userId} />} />
          <Route path="/topics" element={<TopicsPage userId={userId} />} />
          <Route path="/quiz" element={<QuizPage userId={userId} />} />
          <Route path="/planner" element={<PlannerPage userId={userId} />} />
        </Routes>
      </main>
    </div>
  )
}
