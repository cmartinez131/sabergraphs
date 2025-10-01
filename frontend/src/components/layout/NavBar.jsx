import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

export default function NavBar({
  onHomeClick,     // Home passes resetUI; other pages can omit
  onOpenSidebar,   // optional: shows the hamburger and opens the sidebar
  onToggleTheme,   // optional: enables the theme toggle item
  theme = "dark",
}) {
  const [helpOpen, setHelpOpen] = useState(false);
  const helpBtnRef = useRef(null);
  const navigate = useNavigate();

  // Close dropdown on outside click / ESC
  useEffect(() => {
    function onDocClick(e) {
      if (!helpOpen) return;
      if (helpBtnRef.current && !helpBtnRef.current.parentNode.contains(e.target)) {
        setHelpOpen(false);
      }
    }
    function onEsc(e) {
      if (e.key === "Escape") setHelpOpen(false);
    }
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("click", onDocClick);
      document.removeEventListener("keydown", onEsc);
    };
  }, [helpOpen]);

  // Clicking the brand should always take you to a clean Home
  const handleBrandClick = () => {
    if (onHomeClick) {
      onHomeClick(); // Home: fully resets to the starter screen
    } else {
      navigate("/", { replace: true }); // Other pages: just route home
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

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
        <button className="btn light small" type="button">Log in</button>
        <button className="btn primary small" type="button">Sign up for free</button>

        <div className="menu-anchor">
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
              <Link className="menu-item" role="menuitem" to="/pricing" onClick={() => setHelpOpen(false)}>
                See plans & pricing
              </Link>
              <button className="menu-item" role="menuitem" type="button">Settings</button>

              {onToggleTheme && (
                <button
                  className="menu-item"
                  role="menuitem"
                  type="button"
                  onClick={() => {
                    onToggleTheme();
                    setHelpOpen(false);
                  }}
                >
                  {theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
                </button>
              )}

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
      </div>
    </header>
  );
}
