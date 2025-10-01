import React from "react";
import { Link, useNavigate } from "react-router-dom";
import "../App.css";

export default function AboutMe() {
    const navigate = useNavigate();

    return (
        <div className="pricing-page">
            {/* Background */}
            <div className="bg">
                <div className="orb orb-a" />
                <div className="orb orb-b" />
                <div className="orb orb-c" />
                <div className="grain" />
            </div>

            {/* Minimal nav (no Pricing here) */}
            <header className="nav glass">
                <div className="brand">
                    <button
                        className="brand-home"
                        onClick={() => navigate("/")}
                        title="Back to Sabermetric AI"
                    >
                        <div className="logo">⚾︎</div>
                        <span className="brand-title">Sabermetric ai</span>
                    </button>
                </div>
                <div className="nav-actions">
                    <Link className="btn ghost small" to="/">Home</Link>
                    <button className="btn light small" type="button">Log in</button>
                    <button className="btn primary small" type="button">Sign up for free</button>
                </div>
            </header>

            <main className="container pricing">
                {/* Hero */}
                <section className="pricing-hero">
                    <h1>About Me</h1>
                    <p className="muted">Why I’m building Sabermetric AI and where it’s headed.</p>
                </section>

                {/* Content */}
                <section className="glass" style={{ padding: 16 }}>
                    <h3>Background</h3>
                    <p>
                        I’m Christopher Martinez, a graduate student at Georgia Tech, and I'm interested in the intersection of baseball, data, and technology.
                        My interests range from sabermetrics and player development to software engineering, data science,
                        machine learning, and data analysis. Sabermetric AI ties those together with backend systems,
                        data pipelines, and clear data visualizations. I grew up in New York City, a Yankees fan at heart and a baseball fan overall.
                    </p>

                    <h3>Education</h3>
                    <ul className="feature-list">
                        <li><b>B.A. Computer Science</b> — CUNY Hunter College</li>
                        <li><b>M.S. Computer Science</b> (in progress) — Georgia Institute of Technology</li>

                        <li>
                            <b>Coursework</b>: Database Management, Machine Learning, Algorithms, Software Engineering, Artificial Intelligence, Data Mining, Operating Systems, Computer Networks, Calculus 1 & 2, Matrix Algebra, Economic Statistics
                        </li>
                    </ul>

                    <h3>My Toolkit</h3>
                    <ul className="feature-list">
                        <li>
                            <b>Python + data and SQL</b>: I've used Python packages like NumPy, pandas, FastAPI, SQLAlchemy, scikit-learn. I'm comfortable working with SQL and databases.
                            I’ve also taken database management courses, which gave me a strong foundation in relational databases, normalization, indexing, and query optimization. This experience helps me design
                            efficient schemas and write SQL for analytics and application backends.
                        </li>
                        <li>
                            <b>Databases & containerization</b>: Comfortable working with both relational and non-relational databases. I've previously worked with PostgreSQL, Firebase Firestore, and MongoDB. I use Docker for containerizing backend services and streamlining deployment workflows.
                        </li>
                        <li>
                            <b>Real-time and web</b>: I've built full-stack apps with React, Node, and Socket.IO. I use modern charting libraries like Nivo, a JavaScript library for building charts.
                        </li>
                        <li>
                            <b>AI and machine learning</b>: Graduate ML coursework in classification, regression, supervised and unsupervised learning. I apply practical models to baseball data and use the OpenAI API for agentic workflows that turn natural-language queries into real-time analysis and visualizations.
                            I plan to take additional ML courses. I've done projects that applied ML techniques to stock data as part of Graduate ML Work.
                        </li>
                        <li>
                            <b>Some of my other projects (not shown here)</b>:
                            <ul>
                                <li>FastAPI service on AWS for MLB analytics and custom metrics.</li>
                                <li>Full-stack real-time drawing game</li>
                                <li>AI system for a dodgeball video game agent(C#)</li>
                                <li>Experimented with ML models for stock trading</li>
                                <li>Full Stack batting cage booking application</li>
                                <li>Gym Database System from scratch</li>
                            </ul>
                        </li>
                    </ul>

                    <h3>Why Sabermetric AI</h3>
                    <p>
                        This project is a hands-on way for me to go deeper into data analysis, data engineering, visualization,
                        program structure, scalability, APIs, and machine learning, while applying everything to baseball.
                    </p>
                    <ul className="feature-list">
                        <li>
                            <b>Agentic AI</b>: Instead of feeding the entire database to the AI (which is costly and inefficient due to token limits), I use an agentic approach. Written Python functions perform queries on the database, allowing the AI to dynamically handle different natural language queries by selecting and executing the right function. This makes the system more flexible, efficient, and scalable.
                        </li>
                        <li>
                            <b>Supports a variety of queries</b>: The system can handle estimations, player comparisons, advanced metrics, and more.
                        </li>
                        <li>
                            <b>Less clicking, more answers</b>: Baseball Savant is powerful, but moving through
                            multiple dashboards and filters can be tedious. I wanted a dedicated app where a text prompt
                            pulls the right data and returns high quality charts quickly. Data can also be exported as CSV files.
                        </li>
                        <li>
                            <b>Flexible visuals</b>: Charts adapt to the question so different query types can be compared,
                            faceted, or projected without rebuilding a dashboard each time.
                        </li>
                        <li>
                            <b>Work in progress</b>: Pitcher data, More advanced stats, Live pitch data, postseason coverage, and broader query support are on the roadmap.
                        </li>
                    </ul>

                    <h3>Contact</h3>
                    <p>
                        Email: <a href="mailto:chrismartinez131@gmail.com">chrismartinez131@gmail.com</a>
                        <br />
                        Portfolio: <a href="https://chrisamartinez.com" target="_blank" rel="noreferrer">chrisamartinez.com</a>
                        <br />
                        LinkedIn: <a href="https://linkedin.com/in/cmartinez131" target="_blank" rel="noreferrer">linkedin.com/in/cmartinez131</a>
                        <br />
                        GitHub: <a href="https://github.com/cmartinez131" target="_blank" rel="noreferrer">github.com/cmartinez131</a>
                    </p>

                    {/* <p className="muted">
                    Copyright.
                </p> */}
                </section>
            </main>
        </div>
    );
}
