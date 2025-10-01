import React, { useEffect, useState } from "react";
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import "./App.css";

import Home from "./pages/Home";
import Pricing from "./pages/Pricing";
import ProductSpec from "./pages/ProductSpec";
import AboutMe from "./pages/AboutMe";

function useThemeBootstrap() {
  const [theme, setTheme] = useState(
    document.documentElement.dataset.theme || "dark"
  );

  // Initial theme (saved or OS light)
  useEffect(() => {
    const savedTheme = localStorage.getItem("theme");
    if (savedTheme) {
      document.documentElement.dataset.theme = savedTheme;
      setTheme(savedTheme);
      return;
    }
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
      document.documentElement.dataset.theme = "light";
      setTheme("light");
    }
  }, []);

  // Follow OS changes only if the user hasn't picked a theme
  useEffect(() => {
    if (localStorage.getItem("theme")) return;
    if (!window.matchMedia) return;
    const mql = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = (e) => {
      const next = e.matches ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      setTheme(next);
    };
    try {
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    } catch {
      mql.addListener(onChange);
      return () => mql.removeListener(onChange);
    }
  }, []);

  return { theme, setTheme };
}

export default function App() {
  useThemeBootstrap();

  return (
    <Router>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/pricing" element={<Pricing />} />
        <Route path="/product-spec" element={<ProductSpec />} />
        <Route path="/about-me" element={<AboutMe />} />
        <Route path="*" element={<Home />} />
      </Routes>
    </Router>
  );
}
