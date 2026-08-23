// frontend/src/components/layout/NavBar.jsx
import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

export default function NavBar({ onHomeClick, onOpenSidebar }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const mobileBtnRef = useRef(null);
  const navigate = useNavigate();

  // Close the mobile menu on outside click / ESC
  useEffect(() => {
    function onDocClick(e) {
      const clickedMobile =
        mobileBtnRef.current && mobileBtnRef.current.parentNode.contains(e.target);
      if (!clickedMobile) setMobileOpen(false);
    }
    function onEsc(e) {
      if (e.key === "Escape") {
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

  const handleBrandClick = () => {
    if (onHomeClick) onHomeClick();
    else {
      navigate("/", { replace: true });
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
        <button
          className="brand-home"
          onClick={handleBrandClick}
          title="SaberGraphs"
          type="button"
        >
          <div className="logo">⚾︎</div>
          <span className="brand-title">SaberGraphs</span>
        </button>
      </div>

      <div className="nav-actions">
        <button
          className="btn ghost small hide-on-phone"
          type="button"
          onClick={handleBrandClick}
          title="Back to the home page"
        >
          Home
        </button>
        <Link className="btn ghost small hide-on-phone" to="/product-spec" title="Read the product spec">
          Product Spec
        </Link>
        <Link className="btn ghost small hide-on-phone" to="/about-me" title="Read about me page">
          About Me
        </Link>
        {/* <Link className="btn ghost small hide-on-phone" to="/pricing" title="Plans and pricing page">
          Pricing
        </Link> */}

        {/* Auth is not implemented yet; hidden so the nav only shows working features.
        <button className="btn light small hide-on-phone" type="button">Log in</button>
        <button className="btn primary small hide-on-phone" type="button">Sign up for free</button> */}

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
              <button
                className="menu-item"
                role="menuitem"
                type="button"
                onClick={() => {
                  setMobileOpen(false);
                  handleBrandClick();
                }}
              >
                Home
              </button>
              <Link className="menu-item" role="menuitem" to="/product-spec" onClick={() => setMobileOpen(false)}>
                Product Spec
              </Link>
              <Link className="menu-item" role="menuitem" to="/about-me" onClick={() => setMobileOpen(false)}>
                About Me
              </Link>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
