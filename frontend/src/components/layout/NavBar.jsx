// frontend/src/components/layout/NavBar.jsx
import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

export default function NavBar({
  onHomeClick,
  onOpenSidebar,
  onToggleTheme,
  // theme = "dark",  // ← no longer needed; we'll resolve from DOM
}) {
  const [helpOpen, setHelpOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const helpBtnRef = useRef(null);
  const mobileBtnRef = useRef(null);
  const navigate = useNavigate();

  // ---- Resolve current theme from <html data-theme="..."> and keep it in sync
  const getDomTheme = () => {
    const t = document.documentElement.dataset.theme;
    if (t) return t;
    // fallback: OS light/dark if nothing set yet
    try {
      return window.matchMedia &&
        window.matchMedia("(prefers-color-scheme: light)").matches
        ? "light"
        : "dark";
    } catch {
      return "dark";
    }
  };

  const [resolvedTheme, setResolvedTheme] = useState(getDomTheme());

  useEffect(() => {
    const root = document.documentElement;
    const sync = () => setResolvedTheme(getDomTheme());

    // Observe data-theme attribute changes (toggles, OS updates, etc.)
    const mo = new MutationObserver(sync);
    mo.observe(root, { attributes: true, attributeFilter: ["data-theme"] });

    // Also catch cross-tab localStorage changes to "theme"
    const onStorage = (e) => {
      if (e.key === "theme") sync();
    };
    window.addEventListener("storage", onStorage);

    // Initial sync in case something changed before mount
    sync();

    return () => {
      mo.disconnect();
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  // Close menus on outside click / ESC
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

  const handleBrandClick = () => {
    if (onHomeClick) onHomeClick();
    else {
      navigate("/", { replace: true });
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  const ThemeToggleItem = onToggleTheme ? (
    <button
      className="menu-item"
      role="menuitem"
      type="button"
      onClick={() => {
        onToggleTheme?.();
        setHelpOpen(false);
        setMobileOpen(false);
      }}
      aria-label={
        resolvedTheme === "light"
          ? "Switch to dark theme"
          : "Switch to light theme"
      }
    >
      {resolvedTheme === "light" ? "Switch to dark theme" : "Switch to light theme"}
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
        <Link className="btn ghost small hide-on-phone" to="/product-spec" title="Read the product spec">
          Product spec
        </Link>
        <Link className="btn ghost small hide-on-phone" to="/about-me" title="Read about me page">
          About me
        </Link>
        {/* <Link className="btn ghost small hide-on-phone" to="/pricing" title="Plans and pricing page">
          Pricing
        </Link> */}

        <button className="btn light small hide-on-phone" type="button">Log in</button>
        <button className="btn primary small hide-on-phone" type="button">Sign up for free</button>

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
