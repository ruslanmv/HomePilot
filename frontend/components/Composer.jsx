"use client";
import { useState } from "react";
export default function Composer({ onSend }) {
    const [text, setText] = useState("");
    return (<div style={{ display: "flex", gap: 8 }}>
      <input style={{ flex: 1, padding: 8 }} value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask Expert..."/>
      <button onClick={() => {
            if (!text.trim())
                return;
            onSend(text);
            setText("");
        }}>
        Send
      </button>
    </div>);
}
