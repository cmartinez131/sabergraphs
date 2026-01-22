import React from "react";
import { Link, useNavigate } from "react-router-dom";
import "../App.css";
import NavBar from "../components/layout/NavBar";

function toggleTheme() {
  const next =
    document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("theme", next);
}

export default function AboutMe() {
    const navigate = useNavigate();

    return (
        <div className="pricing-page">
            <div className="bg">
                <div className="orb orb-a" />
                <div className="orb orb-b" />
                <div className="orb orb-c" />
                <div className="grain" />
            </div>

            <NavBar onToggleTheme={toggleTheme} />

            <main className="container pricing">
                <section className="pricing-hero">
                    <h1>About Me</h1>
                </section>

                <section className="glass" style={{ padding: 16 }}>
                    <h3>Background</h3>
                    <p>
                        I'm Christopher Martinez, a grad student at Georgia Tech studying computer science with a focus on machine learning. 
                        I grew up in NYC as a Yankees fan and got into sabermetrics through Baseball Reference rabbit holes. 
                        Sabermetric AI is my way of combining baseball and programming.
                    </p>

                    <h3>Education</h3>
                    <ul className="feature-list">
                        <li><b>B.A. Computer Science</b> — CUNY Hunter College</li>
                        <li><b>M.S. Computer Science</b> (in progress) — Georgia Tech, ML specialization</li>
                    </ul>

                    <h3>Skills</h3>
                    <ul className="feature-list">
                        <li><b>Languages</b>: Python, JavaScript, SQL, C#</li>
                        <li><b>ML/Data</b>: scikit-learn, pandas, NumPy, OpenAI API</li>
                        <li><b>Web</b>: React, Node, FastAPI, PostgreSQL, Docker</li>
                    </ul>

                    <h3>Why I Built This</h3>
                    <p>
                        Baseball Savant is great but clicking through dashboards gets tedious. 
                        I wanted something where I could type a question and get a chart back. 
                        The AI doesn't see the whole database. It calls Python functions to run specific queries, 
                        which keeps it fast and cheap on tokens.
                    </p>
                    <p>
                        Still adding pitcher data, more advanced stats, and live pitch tracking.
                    </p>

                    <h3>Contact</h3>
                    <p>
                        <a href="mailto:chrismartinez131@gmail.com">chrismartinez131@gmail.com</a>
                        <br />
                        <a href="https://linkedin.com/in/cmartinez131" target="_blank" rel="noreferrer">LinkedIn</a>
                        {" · "}
                        <a href="https://github.com/cmartinez131" target="_blank" rel="noreferrer">GitHub</a>
                    </p>
                </section>
            </main>
        </div>
    );
}