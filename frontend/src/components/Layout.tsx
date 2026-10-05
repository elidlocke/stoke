import { NavLink, Outlet } from 'react-router'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/top', label: 'Top customers' },
  { to: '/new', label: 'New subscribers' },
  { to: '/anniversaries', label: 'Anniversaries' },
  { to: '/cancellations', label: 'Cancellations' },
]

export function Layout() {
  return (
    <>
      <header className="app-header">
        <div className="app-header-inner">
          <NavLink to="/" className="brand">
            <img src="/favicon.svg" alt="" width={22} height={22} />
            Stoke
          </NavLink>
          <nav aria-label="Main">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end}>
                {n.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main>
        <Outlet />
      </main>
    </>
  )
}
