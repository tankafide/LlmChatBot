import { useEffect, useState } from "react";

// This timer measures the current browser wait, not a provider processing stage.
export function ReplyProgress() {
  const [started] = useState(() => Date.now());
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(
      () => setSeconds(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => clearInterval(timer);
  }, [started]);
  return (
    <>
      <div role="status" aria-live="polite">
        {seconds < 15
          ? "Requesting your AI reply…"
          : seconds < 60
            ? "Your reply is taking longer than usual. The AI service or a vehicle lookup may be slow."
            : "Still waiting for a confirmed result. You can keep this page open; if the connection times out, use Check reply to recover the outcome."}
      </div>
      <span aria-live="off">Waiting {seconds}s</span>
    </>
  );
}
