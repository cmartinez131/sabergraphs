import React from "react";
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import "./App.css";

import Home from "./pages/Home";
import Pricing from "./pages/Pricing";
import ProductSpec from "./pages/ProductSpec";
import AboutMe from "./pages/AboutMe";

export default function App() {
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
