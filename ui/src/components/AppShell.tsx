import { NavLink, Outlet } from "react-router-dom";

export function AppShell() {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="product">OCTOPUS</div>
        <div className="product-subtitle">Board Console</div>
        <nav className="global-nav" aria-label="主导航">
          <NavLink to="/organizations">组织</NavLink>
        </nav>
      </aside>
      <main className="workspace">
        <Outlet />
      </main>
    </div>
  );
}
