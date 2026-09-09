import { NavLink } from 'react-router-dom'

export default function SiteNav() {
  return (
    <nav className="site-nav">
      <NavLink to="/" className="brand">
        <span className="brand-mark">FinGuard</span>
        <span className="brand-tag">Risk Intelligence</span>
      </NavLink>
      <div className="site-nav-links">
        <NavLink to="/app" className={({ isActive }) => (isActive ? 'active' : '')}>
          Watchlist
        </NavLink>
        <NavLink to="/about" className={({ isActive }) => (isActive ? 'active' : '')}>
          How it works
        </NavLink>
        <a
          href="https://github.com/goeldaksh06/FinguardAI"
          target="_blank"
          rel="noreferrer"
          className="site-nav-cta"
          style={{ borderRadius: 8, padding: '8px 14px' }}
        >
          GitHub
        </a>
      </div>
    </nav>
  )
}
