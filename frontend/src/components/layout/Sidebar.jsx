import React from "react";

export default function Sidebar({ open, onClose, conversations, onSelectConversation, loggedIn, onNewChat }) {
  return (
    <>
      <aside className={`sidebar glass ${open ? "open" : ""}`} aria-hidden={!open}>
        <div className="sidebar-head">
          <div className="sidebar-title">Conversations</div>
          <button className="icon-btn" onClick={onClose} aria-label="Close sidebar">✕</button>
        </div>

        <button className="btn primary new-chat" type="button" onClick={onNewChat}>
          + New chat
        </button>

        <div className="conv-list">
          {conversations.map((c) => (
            <button
              key={c.id}
              className="conv-item"
              type="button"
              onClick={() => onSelectConversation(c)}
            >
              <div className="conv-title">{c.title}</div>
              <div className="conv-meta">{c.updated}</div>
            </button>
          ))}
        </div>

        <div className="sidebar-foot">
          <span className="sync-note">{loggedIn ? "Synced to your account" : "Sign in to sync chats"}</span>
          <button className="btn ghost small" type="button">
            {loggedIn ? "Account" : "Sign in"}
          </button>
        </div>
      </aside>
      {open && <div className="scrim" onClick={onClose} />}
    </>
  );
}
