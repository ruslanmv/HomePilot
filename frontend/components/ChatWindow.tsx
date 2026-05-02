"use client";

import { useEffect, useRef, useState } from "react";
import MessageList from "./MessageList";
import Composer from "./Composer";

type ActivityStage = "idle" | "parsing" | "thinking";

function ExpertActivity({ stage }: { stage: ActivityStage }) {
  if (stage === "idle") return null;

  const isParsing = stage === "parsing";

  return (
    <div
      style={{
        background: "#080808",
        borderRadius: 16,
        padding: "16px 18px",
        marginBottom: 14,
        border: "1px solid rgba(60,60,70,0.35)",
        color: "#ddd",
      }}
    >
      <style>{`
        @keyframes hpDotBounce {
          0%, 80%, 100% { transform: translateY(0); opacity: 0.7; }
          40% { transform: translateY(-6px); opacity: 1; }
        }
        @keyframes hpGrokPulse {
          0% { background: #222; transform: scale(1); opacity: .75; box-shadow: 0 0 2px rgba(255,255,255,.1); }
          8% { background: #fff; transform: scale(1.55); opacity: 1; box-shadow: 0 0 8px rgba(255,255,255,.9), 0 0 14px rgba(180,220,255,.6); }
          18% { background: #aaa; transform: scale(1.15); opacity: .9; box-shadow: 0 0 4px rgba(255,255,255,.4); }
          28%, 100% { background: #222; transform: scale(1); opacity: .75; box-shadow: 0 0 2px rgba(255,255,255,.08); }
        }
      `}</style>
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 10 }}>
        {isParsing ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 5px)", gridTemplateRows: "repeat(3, 5px)", gap: 7 }}>
            {Array.from({ length: 9 }).map((_, i) => (
              <span
                key={i}
                style={{
                  width: 5,
                  height: 5,
                  borderRadius: "50%",
                  animation: "hpGrokPulse 2.4s infinite ease-in-out",
                  animationDelay: `${i * 0.2}s`,
                }}
              />
            ))}
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: "#888",
                  animation: "hpDotBounce 1.3s infinite ease-in-out",
                  animationDelay: `${i * 0.15}s`,
                }}
              />
            ))}
          </div>
        )}
        <div style={{ color: "#7aaae0", fontSize: 15 }}>
          {isParsing ? "Parsing question · sending to backend" : "Thinking"}
        </div>
      </div>
      <div style={{ color: "#8e8e9a", fontSize: 13 }}>
        {isParsing
          ? "Analyzing query structure and preparing tool context."
          : "Processing reasoning step-by-step."}
      </div>
    </div>
  );
}

export default function ChatWindow() {
  const [messages, setMessages] = useState<string[]>([]);
  const [stage, setStage] = useState<ActivityStage>("idle");
  const parseTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (parseTimer.current) clearTimeout(parseTimer.current);
    };
  }, []);

  async function sendMessage(text: string) {
    setStage("parsing");
    parseTimer.current = setTimeout(() => setStage("thinking"), 1200);

    try {
      const resp = await fetch("http://localhost:8000/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: "default", message: text }),
      });
      const data = await resp.json();

      if (parseTimer.current) clearTimeout(parseTimer.current);
      setStage("thinking");

      setMessages((prev) => [...prev, `User: ${text}`, `Expert: ${data.answer}`]);
    } catch (err) {
      if (parseTimer.current) clearTimeout(parseTimer.current);
      setMessages((prev) => [...prev, `User: ${text}`, `Expert: Failed to get response: ${String(err)}`]);
    } finally {
      setStage("idle");
    }
  }

  return (
    <div style={{ padding: 24 }}>
      <MessageList messages={messages} />
      <ExpertActivity stage={stage} />
      <Composer onSend={sendMessage} />
    </div>
  );
}
