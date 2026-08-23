import React from "react";
import "../App.css";
import NavBar from "../components/layout/NavBar";

export default function AboutMe() {
    return (
        <div className="pricing-page">
            <div className="bg">
                <div className="orb orb-a" />
                <div className="orb orb-b" />
                <div className="orb orb-c" />
                <div className="grain" />
            </div>

            <NavBar />

            <main className="container pricing">
                <section className="pricing-hero">
                    <h1>About Me</h1>
                </section>

                <section className="glass" style={{ padding: 16 }}>
                    <h3>Background</h3>
                    <p>
                        I'm Christopher Martinez, a grad student at Georgia Tech studying computer science with a specialization in artificial intelligence. 
                        I grew up in NYC as a Yankees fan and got into sabermetrics through Baseball Reference rabbit holes. 
                        SaberGraphs is my way of combining baseball and programming.
                    </p>

                    <h3>Education</h3>
                    <ul className="feature-list">
                        <li>
                            <b>M.S. Computer Science</b>, Georgia Tech, specialization in artificial intelligence (expected May 2027)
                            <br />
                            <span className="muted">Courses: Machine Learning for Trading, Natural Language Processing, Computer Vision, Human-Computer Interaction</span>
                        </li>
                        <li>
                            <b>B.A. Computer Science</b>, CUNY Hunter College (2023)
                            <br />
                            <span className="muted">Courses: Software Engineering, Web Development, Database Management, Data Structures and Algorithms</span>
                        </li>
                    </ul>

                    <h3>Skills</h3>
                    <ul className="feature-list">
                        <li><b>Languages</b>: Python, TypeScript, JavaScript, SQL, C/C++</li>
                        <li><b>Frameworks and Libraries</b>: FastAPI, React, Next.js, Node.js, pandas, NumPy, scikit-learn</li>
                        <li><b>Data and Infrastructure</b>: PostgreSQL, AWS S3, Google Cloud Storage, Docker, Git, Linux</li>
                        <li><b>AI and ML</b>: LLM integration, RAG, supervised learning, reinforcement learning, prompt engineering, Claude API, Gemini</li>
                    </ul>

                    <h3>Why I Built This</h3>
                    <p>
                        Baseball Savant is great but clicking through dashboards gets tedious, especially for someone who is non-technical. 
                        I wanted something where I could type a question and get a chart back. 
                        The AI never invents numbers. It either writes a SQL query that is safety checked and 
                        run read-only, or calls analytics functions, so every number on a chart comes straight 
                        from the database.
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
