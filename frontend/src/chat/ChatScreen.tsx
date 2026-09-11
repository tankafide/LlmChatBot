import {
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
} from "@assistant-ui/react";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { ChatRuntime } from "./runtime";
import { useConversation } from "./useConversation";
import { ReplyProgress } from "./ReplyProgress";
import { failureReason } from "./requestFeedback";

const RevealRequestContext = createContext<string | undefined>(undefined);

function FastRevealText({ text }: { text: string }) {
  const [visibleLength, setVisibleLength] = useState(0);
  const complete = visibleLength >= text.length;

  useEffect(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setVisibleLength(text.length);
      return;
    }
    setVisibleLength(0);
    const duration = Math.min(700, Math.max(220, text.length * 1.5));
    const started = performance.now();
    let frame = 0;
    const reveal = (now: number) => {
      const progress = Math.min(1, (now - started) / duration);
      setVisibleLength(Math.ceil(text.length * progress));
      if (progress < 1) frame = requestAnimationFrame(reveal);
    };
    frame = requestAnimationFrame(reveal);
    return () => cancelAnimationFrame(frame);
  }, [text]);

  return (
    <span className="fast-reveal" data-revealing={!complete} aria-live="off">
      {text.slice(0, visibleLength)}
      {!complete && <span className="reveal-caret" aria-hidden="true" />}
    </span>
  );
}

function StoredMessage() {
  const message = useAuiState((s) => s.message);
  const revealRequestId = useContext(RevealRequestContext);
  const status = message.metadata.custom.requestStatus;
  const text = message.content
    .map((part) => (part.type === "text" ? part.text : ""))
    .join("");
  const reveal =
    message.role === "assistant" &&
    message.metadata.custom.requestId === revealRequestId;
  return (
    <MessagePrimitive.Root
      className={`message ${message.role}`}
      data-message-id={message.id}
      data-request-id={message.metadata.custom.requestId}
    >
      <span className="speaker">
        {message.role === "user" ? "You" : "AutoAssist"}
      </span>
      <div className="message-text">
        {reveal ? <FastRevealText text={text} /> : <MessagePrimitive.Parts />}
      </div>
      {message.role === "user" && status === "in_progress" && (
        <p className="message-status">Accepted · Reply in progress</p>
      )}
      {message.role === "user" && status === "failed" && (
        <p className="message-status">
          Reply failed · No reply was saved.{" "}
          {failureReason(message.metadata.custom.errorCode)}
        </p>
      )}
      {message.role === "user" && status === "interrupted" && (
        <p className="message-status">Reply interrupted · No reply was saved</p>
      )}
    </MessagePrimitive.Root>
  );
}
export function ChatScreen() {
  const chat = useConversation();
  const viewport = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const programmaticScroll = useRef(false);
  const pendingPositioned = useRef<string | undefined>(undefined);
  const replyPositioned = useRef<string | undefined>(undefined);
  const historyPositioned = useRef(false);
  const autoPositionReply = useRef(true);
  const input = useRef<HTMLTextAreaElement>(null);
  const [showJump, setShowJump] = useState(false);
  const locked = !chat.ready || chat.busy || !!chat.pending || chat.missing;
  const optimisticUser =
    chat.pending &&
    !chat.messages.some((m) => m.request_id === chat.pending?.request_id);
  const latestUser = [...chat.messages]
    .reverse()
    .find((m) => m.role === "user");
  const lastFailed =
    latestUser &&
    (latestUser.request_status === "failed" ||
      latestUser.request_status === "interrupted")
      ? latestUser
      : undefined;

  const revealRequestId = chat.latestSubmittedRequestId;

  function positionElement(target: Element, viewportFraction: number) {
    const el = viewport.current;
    if (!el) return;
    const viewportRect = el.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    programmaticScroll.current = true;
    el.scrollTop = Math.max(
      0,
      el.scrollTop +
        targetRect.top -
        viewportRect.top -
        el.clientHeight * viewportFraction,
    );
    requestAnimationFrame(() => {
      programmaticScroll.current = false;
    });
  }

  useEffect(() => {
    const requestId = chat.pending?.request_id;
    if (!requestId || pendingPositioned.current === requestId) return;
    pendingPositioned.current = requestId;
    autoPositionReply.current = follow.current;
    setShowJump(false);
    if (follow.current) {
      const pending = viewport.current?.querySelector(".optimistic-user");
      if (pending) positionElement(pending, 0.22);
    }
  }, [chat.pending]);

  useEffect(() => {
    const requestId = chat.latestSubmittedRequestId;
    if (!requestId) {
      const el = viewport.current;
      if (
        !historyPositioned.current &&
        chat.ready &&
        chat.messages.length &&
        el
      ) {
        const frame = requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            historyPositioned.current = true;
            programmaticScroll.current = true;
            el.scrollTop = el.scrollHeight;
            requestAnimationFrame(() => {
              programmaticScroll.current = false;
            });
          });
        });
        return () => cancelAnimationFrame(frame);
      }
      return;
    }
    const assistant = chat.messages.find(
      (message) =>
        message.role === "assistant" && message.request_id === requestId,
    );
    if (!assistant || replyPositioned.current === assistant.id) return;
    const frame = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const target = viewport.current?.querySelector(
          `[data-message-id="${assistant.id}"]`,
        );
        if (!target) return;
        replyPositioned.current = assistant.id;
        if (autoPositionReply.current) {
          follow.current = true;
          positionElement(target, 0.06);
        } else {
          setShowJump(true);
        }
        input.current?.focus({ preventScroll: true });
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [chat.latestSubmittedRequestId, chat.messages, chat.ready]);

  function jumpToLatestReply() {
    const id = replyPositioned.current;
    const target = id
      ? viewport.current?.querySelector(`[data-message-id="${id}"]`)
      : undefined;
    if (!target) return;
    follow.current = true;
    setShowJump(false);
    positionElement(target, 0.06);
  }

  return (
    <ChatRuntime messages={chat.messages} busy={chat.busy} send={chat.send}>
      <RevealRequestContext.Provider value={revealRequestId}>
        <div className="app-shell">
          <header>
            <div className="brand">
              <span className="mark" aria-hidden="true">
                A
              </span>
              <div>
                <strong>AutoAssist</strong>
                <span className="dealer">
                  {chat.dealer?.name ?? "Dealership chat"}
                </span>
              </div>
            </div>
            <button
              className="new-chat"
              onClick={chat.newChat}
              disabled={
                !chat.missing && (chat.busy || !!chat.pending || !chat.ready)
              }
            >
              New chat
            </button>
          </header>
          <main>
            <ThreadPrimitive.Root className="thread">
              <div className="transcript-shell">
                <div
                  ref={viewport}
                  className="transcript"
                  role="region"
                  aria-label="Conversation"
                  tabIndex={0}
                  onScroll={() => {
                    const el = viewport.current;
                    if (!el || programmaticScroll.current) return;
                    follow.current =
                      el.scrollHeight - el.scrollTop - el.clientHeight < 64;
                    if (follow.current) setShowJump(false);
                  }}
                >
                  <div className="reading-column">
                    {!chat.messages.length && !optimisticUser && (
                      <section className="intro">
                        <p className="eyebrow">
                          YOUR NEXT CAR STARTS WITH A CONVERSATION
                        </p>
                        <h1>What are you looking for?</h1>
                        <p>
                          Explore our inventory, get to know a vehicle, or ask
                          about recalls and crash-test ratings.
                        </p>
                        <p className="example">
                          Try “Show me Toyota SUVs under $35,000.”
                        </p>
                      </section>
                    )}
                    <ThreadPrimitive.Messages
                      components={{ Message: StoredMessage }}
                    />
                    {optimisticUser && (
                      <section
                        className="message user optimistic-user"
                        data-request-id={chat.pending?.request_id}
                      >
                        <span className="speaker">You</span>
                        <div className="message-text">{chat.pending?.text}</div>
                        {!chat.busy && (
                          <p
                            className="message-status"
                            role="status"
                            aria-live="polite"
                          >
                            {chat.notice ||
                              (chat.pendingState === "unaccepted"
                                ? "Not sent. The server is busy; use Check reply to retry this message."
                                : chat.pendingState === "accepted"
                                  ? "Accepted. The reply is still in progress; use Check reply to check again."
                                  : "Delivery is unconfirmed; use Check reply to recover this message.")}
                          </p>
                        )}
                      </section>
                    )}
                  </div>
                </div>
                {showJump && (
                  <button className="jump-latest" onClick={jumpToLatestReply}>
                    Jump to latest
                  </button>
                )}
              </div>
              <div className="composer-area">
                {chat.storageWarning && (
                  <p className="warning">
                    Browser storage is unavailable. Chat can continue, but
                    recovery after reload is not guaranteed.
                  </p>
                )}
                <div className="status">
                  {chat.busy && chat.pending ? (
                    <ReplyProgress key={chat.pending.request_id} />
                  ) : (
                    <div
                      role={optimisticUser ? undefined : "status"}
                      aria-live={optimisticUser ? undefined : "polite"}
                    >
                      {chat.busy
                        ? "Connecting and loading conversation…"
                        : (!optimisticUser && chat.notice) ||
                          (chat.pending
                            ? "Reply unconfirmed. Check reply to recover this message."
                            : "")}
                    </div>
                  )}
                </div>
                <div className="recovery">
                  {!chat.missing &&
                    !chat.busy &&
                    (!chat.ready || chat.pending) && (
                      <button onClick={() => void chat.check()}>
                        {chat.cursor !== null
                          ? "Continue loading"
                          : chat.pending
                            ? "Check reply"
                            : "Retry connection"}
                      </button>
                    )}
                  {!locked && lastFailed && (
                    <button
                      onClick={() => {
                        chat.setDraft(lastFailed.text);
                        input.current?.focus();
                      }}
                    >
                      Try again
                    </button>
                  )}
                </div>
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    void chat.send();
                  }}
                >
                  <label htmlFor="message">
                    Message {chat.dealer?.name ?? "AutoAssist"}
                  </label>
                  <textarea
                    ref={input}
                    id="message"
                    placeholder="Ask about a vehicle…"
                    rows={3}
                    maxLength={4000}
                    value={chat.draft}
                    readOnly={locked}
                    aria-describedby="composer-help"
                    onChange={(event) => chat.setDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (
                        event.key === "Enter" &&
                        !event.shiftKey &&
                        !event.nativeEvent.isComposing &&
                        event.keyCode !== 229
                      ) {
                        event.preventDefault();
                        void chat.send();
                      }
                    }}
                  />
                  <div className="composer-footer">
                    <span id="composer-help">
                      Shift + Enter for a new line · {chat.draft.length}/4,000
                    </span>
                    <button
                      className="send"
                      type="submit"
                      disabled={locked || !chat.draft.trim()}
                    >
                      Send <span aria-hidden="true">↑</span>
                    </button>
                  </div>
                </form>
                <p className="footnote">
                  Vehicle and safety information comes from inventory and NHTSA.
                  Ask for details before making a decision.
                </p>
              </div>
            </ThreadPrimitive.Root>
          </main>
        </div>
      </RevealRequestContext.Provider>
    </ChatRuntime>
  );
}
