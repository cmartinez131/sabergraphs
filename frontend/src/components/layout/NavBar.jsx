// frontend/src/components/layout/NavBar.jsx
import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

export default function NavBar({
  onHomeClick,     // Home passes resetUI; other pages can omit
  onOpenSidebar,   // optional: shows the hamburger and opens the sidebar
  onToggleTheme,   // optional: enables the theme toggle item
  theme = "dark",
}) {
  const [helpOpen, setHelpOpen] = useState(false);          // desktop "?" menu
  const [mobileOpen, setMobileOpen] = useState(false);      // phone "⋯" menu
  const helpBtnRef = useRef(null);
  const mobileBtnRef = useRef(null);
  const navigate = useNavigate();

  // Close any open menu on outside click / ESC
  useEffect(() => {
    function onDocClick(e) {
      const clickedHelp =
        helpBtnRef.current && helpBtnRef.current.parentNode.contains(e.target);
      const clickedMobile =
        mobileBtnRef.current && mobileBtnRef.current.parentNode.contains(e.target);

      if (!clickedHelp) setHelpOpen(false);
      if (!clickedMobile) setMobileOpen(false);
    }
    function onEsc(e) {
      if (e.key === "Escape") {
        setHelpOpen(false);
        setMobileOpen(false);
      }
    }
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("click", onDocClick);
      document.removeEventListener("keydown", onEsc);
    };
  }, []);

  // Clicking the brand should always take you to a clean Home
  const handleBrandClick = () => {
    if (onHomeClick) {
      onHomeClick(); // Home: fully resets to the starter screen
    } else {
      navigate("/", { replace: true }); // Other pages: just route home
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  const ThemeToggleItem = onToggleTheme ? (
    <button
      className="menu-item"
      role="menuitem"
      type="button"
      onClick={() => {
        onToggleTheme();
        setHelpOpen(false);
        setMobileOpen(false);
      }}
    >
      {theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
    </button>
  ) : null;

  return (
    <header className="nav glass">
      <div className="brand">
        {onOpenSidebar && (
          <button
            className="icon-btn"
            aria-label="Open sidebar"
            onClick={onOpenSidebar}
            title="Conversations"
            type="button"
          >
            ☰
          </button>
        )}

        {/* Button avoids underline styling and lets us run reset logic */}
        <button className="brand-home" onClick={handleBrandClick} title="New chat (Home)" type="button">
          <div className="logo">⚾︎</div>
          <span className="brand-title">sabermetric ai</span>
        </button>
      </div>

      <div className="nav-actions">
        {/* Desktop/tablet actions */}
        <Link className="btn ghost small hide-on-phone" to="/product-spec" title="Read the product spec">
          Product spec
        </Link>
        <Link className="btn ghost small hide-on-phone" to="/about-me" title="Read about me page">
          About me
        </Link>

        <button className="btn light small hide-on-phone" type="button">Log in</button>
        <button className="btn primary small hide-on-phone" type="button">Sign up for free</button>

        {/* Desktop help menu ("?") */}
        <div className="menu-anchor hide-on-phone">
          <button
            ref={helpBtnRef}
            className="icon-btn circle"
            aria-haspopup="menu"
            aria-expanded={helpOpen}
            onClick={(e) => {
              e.stopPropagation();
              setHelpOpen((v) => !v);
            }}
            title="Help & more"
            type="button"
          >
            ?
          </button>

          {helpOpen && (
            <div className="menu glass" role="menu">
              {/* <Link className="menu-item" role="menuitem" to="/pricing" onClick={() => setHelpOpen(false)}>
                See plans & pricing
              </Link> */}
              {ThemeToggleItem}
              <div className="menu-divider" />
              <Link className="menu-item" role="menuitem" to="/product-spec" onClick={() => setHelpOpen(false)}>
                Product Spec
              </Link>
              <Link className="menu-item" role="menuitem" to="/about-me" onClick={() => setHelpOpen(false)}>
                About me
              </Link>
            </div>
          )}
        </div>

        {/* Phone-only compact actions (⋯) */}
        <div className="menu-anchor show-on-phone">
          <button
            ref={mobileBtnRef}
            className="icon-btn circle"
            aria-haspopup="menu"
            aria-expanded={mobileOpen}
            onClick={(e) => {
              e.stopPropagation();
              setMobileOpen((v) => !v);
            }}
            title="Menu"
            type="button"
          >
            ⋯
          </button>

          {mobileOpen && (
            <div className="menu glass" role="menu">
              <Link className="menu-item" role="menuitem" to="/product-spec" onClick={() => setMobileOpen(false)}>
                Product spec
              </Link>
              <Link className="menu-item" role="menuitem" to="/about-me" onClick={() => setMobileOpen(false)}>
                About me
              </Link>

              <div className="menu-divider" />

              {/* <Link className="menu-item" role="menuitem" to="/pricing" onClick={() => setMobileOpen(false)}>
                See plans & pricing
              </Link> */}
              {ThemeToggleItem}

              <div className="menu-divider" />

              <button className="menu-item" type="button" onClick={() => setMobileOpen(false)}>
                Log in
              </button>
              <button className="menu-item" type="button" onClick={() => setMobileOpen(false)}>
                Sign up for free
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
