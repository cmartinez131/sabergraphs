import React, { useEffect, useRef, useState } from "react";

export default function Sidebar({
  open,
  onClose,
  conversations,
  onSelectConversation,
  onDeleteConversation, // called with (id)
  loggedIn,
  onNewChat,
}) {
  const [menuFor, setMenuFor] = useState(null); // active convo id
  const rootRef = useRef(null);

  // Close the popover when clicking outside the sidebar
  useEffect(() => {
    function onDocClick(e) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(e.target)) setMenuFor(null);
    }
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  return (
    <>
      <aside
        ref={rootRef}
        className={`sidebar glass ${open ? "open" : ""}`}
        aria-hidden={!open}
      >
        <div className="sidebar-head">
          <div className="sidebar-title">Conversations</div>
          <button className="icon-btn" onClick={onClose} aria-label="Close sidebar">
            ✕
          </button>
        </div>

        <button className="btn primary new-chat" type="button" onClick={onNewChat}>
          + New chat
        </button>

        <div className="conv-list" role="list" aria-label="Conversations list">
          {conversations.map((c) => {
            const isOpen = menuFor === c.id;
            return (
              <div key={c.id} className={`conv-entry ${isOpen ? "with-popover" : ""}`}>
                {/* Main conversation button */}
                <button
                  className="conv-item"
                  type="button"
                  role="listitem"
                  onClick={() => {
                    setMenuFor(null);
                    onSelectConversation(c);
                  }}
                  title={c.title}
                >
                  <div className="conv-title">{c.title}</div>
                  <div className="conv-meta">{c.updated}</div>
                </button>

                {/* 3-dot button + tiny destructive popover */}
                <div className="menu-anchor">
                  <button
                    className="icon-btn circle dot-btn"
                    type="button"
                    aria-label="Conversation options"
                    aria-expanded={isOpen}
                    onClick={(e) => {
                      e.stopPropagation();
                      setMenuFor((m) => (m === c.id ? null : c.id));
                    }}
                  >
                    ⋯
                  </button>

                  {isOpen && (
                    <div
                      className="conv-popover"
                      role="menu"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <button
                        className="pop-item danger"
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          // immediate delete, no confirm
                          setMenuFor(null);
                          onDeleteConversation?.(c.id);
                        }}
                      >
                        <span className="pop-icon" aria-hidden>🗑️</span>
                        Delete
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className="sidebar-foot">
          <span className="sync-note">
            {loggedIn ? "Synced to your account" : "Sign in to sync chats"}
          </span>
          <button className="btn ghost small" type="button">
            {loggedIn ? "Account" : "Sign in"}
          </button>
        </div>
      </aside>

      {open && <div className="scrim" onClick={onClose} />}
    </>
  );
}
