export default function MessageList({ messages }: { messages: string[] }) {
  return (
    <div style={{ marginBottom: 16 }}>
      {messages.map((m, i) => (
        <div key={i} style={{ padding: 8, borderBottom: "1px solid #ddd" }}>
          {m}
        </div>
      ))}
    </div>
  );
}
