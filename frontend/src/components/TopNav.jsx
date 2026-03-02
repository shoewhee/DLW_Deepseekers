import { NavLink } from 'react-router-dom'

const navItems = [
  { to: '/', label: 'Dashboard' },
  { to: '/topics', label: 'Topics & Notes' },
  { to: '/quiz', label: 'Quiz Runner' },
  { to: '/planner', label: 'Study Planner' },
]

export default function TopNav({ userEmail }) {
  return (
    <header className="top-nav">
      <div className="brand">
        <h2>Learning Control Center</h2>
        <p>{userEmail}</p>
      </div>

      <nav>
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) => (isActive ? 'nav-pill active' : 'nav-pill')}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </header>
  )
}
