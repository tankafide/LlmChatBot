import { useEffect, useRef, useState } from "react";
import { failureReason } from "./requestFeedback";
import {
  api,
  ApiError,
  record,
  uuid,
  type Dealer,
  type Message,
  type Submission,
} from "../api/client";

type Pending = Submission & { conversation: string };
type State = {
  dealer?: Dealer;
  conversation?: string;
  creationId?: string;
  messages: Message[];
  pending?: Pending;
  latestSubmittedRequestId?: string;
  pendingState: "unconfirmed" | "unaccepted" | "accepted";
  draft: string;
  busy: boolean;
  ready: boolean;
  missing: boolean;
  notice: string;
  storageWarning: boolean;
  cursor: number | null;
};
const initial = (): State => ({
  dealer: undefined,
  conversation: undefined,
  creationId: undefined,
  pending: undefined,
  latestSubmittedRequestId: undefined,
  pendingState: "unconfirmed",
  messages: [],
  draft: "",
  busy: false,
  ready: false,
  missing: false,
  notice: "",
  storageWarning: false,
  cursor: null,
});
const terminal = (m: Message) => m.request_status !== "in_progress";
export function mergeMessages(
  previous: Message[],
  incoming: Message[],
): Message[] {
  const map = new Map(previous.map((m) => [m.id, m]));
  for (const m of incoming) {
    const old = map.get(m.id);
    map.set(m.id, old && terminal(old) && !terminal(m) ? old : m);
  }
  return [...map.values()].sort((a, b) => a.sequence - b.sequence);
}
export function useConversation() {
  const [state, render] = useState<State>(initial);
  const current = useRef(state);
  const generation = useRef(0);
  const outcomes = useRef(
    new Map<
      string,
      { status: Message["request_status"]; code: string | null }
    >(),
  );
  const key = `autoassist:${location.origin}:mia-motors`;
  function update(patch: Partial<State>) {
    current.current = { ...current.current, ...patch };
    render(current.current);
  }
  function persist() {
    const s = current.current;
    try {
      if (s.conversation || s.creationId)
        localStorage.setItem(
          key,
          JSON.stringify({
            conversation: s.conversation,
            pending: s.pending,
            creationId: s.creationId,
          }),
        );
      else localStorage.removeItem(key);
    } catch {
      update({ storageWarning: true });
    }
  }
  function reconcile() {
    const s = current.current;
    const found = s.messages.find(
      (m) => m.role === "user" && m.request_id === s.pending?.request_id,
    );
    if (found && terminal(found) && found.text === s.pending?.text)
      update({
        pending: undefined,
        notice:
          found.request_status === "completed"
            ? "Reply saved."
            : found.request_status === "failed"
              ? `${failureReason(found.error_code)} Your message is saved. Try again to prepare a new attempt.`
              : "The reply was interrupted. Try again to prepare a new attempt.",
      });
    if (!current.current.pending) {
      const active = s.messages.find((m) => m.role === "user" && !terminal(m));
      if (active && s.conversation)
        update({
          pending: {
            conversation: s.conversation,
            request_id: active.request_id,
            text: active.text,
          },
        });
    }
    persist();
  }
  function fail(error: unknown) {
    if (
      error instanceof ApiError &&
      error.status === 404 &&
      error.code === "not_found"
    )
      update({
        missing: true,
        notice:
          "This conversation is unavailable. Start a new chat to recover your draft.",
      });
    else
      update({
        notice:
          error instanceof Error
            ? error.message
            : "Unable to load the conversation.",
      });
  }
  async function load(view: number, after: number) {
    const { dealer, conversation } = current.current;
    if (!dealer || !conversation) return;
    update({ ready: false, cursor: after });
    try {
      for (let page = 0; page < 10; page++) {
        const result = await api.history(dealer.id, conversation, after);
        if (view !== generation.current) return;
        update({
          messages: mergeMessages(
            current.current.messages,
            result.items.map((m) => {
              const outcome = outcomes.current.get(m.request_id);
              return outcome && !terminal(m)
                ? {
                    ...m,
                    request_status: outcome.status,
                    error_code: outcome.code,
                  }
                : m;
            }),
          ),
          cursor: result.next_after_sequence,
        });
        if (result.next_after_sequence === null) {
          reconcile();
          update({ ready: true });
          return;
        }
        after = result.next_after_sequence;
      }
      update({
        notice: "More history is available. Continue loading before sending.",
      });
    } catch (error) {
      if (view === generation.current) fail(error);
    }
  }
  async function initialize(view: number) {
    update({ busy: true, notice: "" });
    try {
      const dealer = await api.dealership();
      if (view !== generation.current) return;
      update({ dealer });
      try {
        const raw = localStorage.getItem(key);
        const saved: unknown = raw ? JSON.parse(raw) : null;
        if (record(saved) && uuid(saved.creationId))
          update({ creationId: saved.creationId });
        if (record(saved) && uuid(saved.conversation)) {
          let pending: Pending | undefined;
          const p = saved.pending;
          if (
            record(p) &&
            p.conversation === saved.conversation &&
            uuid(p.request_id) &&
            typeof p.text === "string" &&
            p.text.trim() &&
            p.text.length <= 4000
          )
            pending = {
              conversation: saved.conversation,
              request_id: p.request_id,
              text: p.text,
            };
          update({
            conversation: saved.conversation,
            pending,
          });
        }
      } catch {
        update({ storageWarning: true });
      }
      if (current.current.conversation) {
        await load(view, 0);
        const pending = current.current.pending;
        if (
          view === generation.current &&
          current.current.ready &&
          pending &&
          current.current.messages.some(
            (m) => m.request_id === pending.request_id && !terminal(m),
          )
        )
          await post(pending, view, true);
      } else update({ ready: true });
    } catch (error) {
      if (view === generation.current) fail(error);
    } finally {
      if (view === generation.current) update({ busy: false });
    }
  }
  useEffect(() => {
    const view = ++generation.current;
    void initialize(view);
    return () => {
      generation.current++;
    };
    // One bootstrap per view; mutations run only from deliberate actions.
    // eslint does not enable exhaustive-deps: the controller reads its current ref.
  }, []);

  async function poll(pending: Pending, view: number) {
    const dealer = current.current.dealer;
    if (!dealer) return;
    for (let attempt = 0; attempt < 20; attempt++) {
      if (view !== generation.current) return;
      const result = await api.status(dealer.id, pending.conversation, pending);
      if (view !== generation.current) return;
      if (result.status === "completed") return result.outcome;
      if (result.status !== "in_progress") {
        const code = result.outcome.error.code;
        outcomes.current.set(pending.request_id, {
          status: result.status,
          code,
        });
        update({
          messages: current.current.messages.map((m) =>
            m.request_id === pending.request_id
              ? { ...m, request_status: result.status, error_code: code }
              : m,
          ),
          pending: undefined,
          notice:
            result.status === "failed"
              ? `${failureReason(code)} Your message is saved. Try again to prepare a new attempt.`
              : "The reply was interrupted. Try again to prepare a new attempt.",
        });
        persist();
        return;
      }
      if (attempt < 19)
        await new Promise((resolve) =>
          setTimeout(resolve, Math.min(500 * 2 ** attempt, 5000)),
        );
    }
    update({
      notice: "The reply is still unconfirmed. Use Check reply to check again.",
    });
  }

  async function post(pending: Pending, view: number, accepted = false) {
    const dealer = current.current.dealer;
    if (!dealer) return;
    try {
      const admission = accepted
        ? undefined
        : await api.send(dealer.id, pending.conversation, {
            request_id: pending.request_id,
            text: pending.text,
          });
      if (view !== generation.current) return;
      let reply;
      if (!admission || "status" in admission) {
        update({
          pendingState: "accepted",
          notice: "Your message was accepted and is preparing a reply.",
        });
        const known = current.current.messages.find(
          (m) => m.request_id === pending.request_id,
        );
        await load(view, known ? known.sequence - 1 : 0);
        if (view !== generation.current) return;
        if (current.current.ready && !current.current.pending) return;
        reply = await poll(pending, view);
        if (!reply) return;
      } else reply = admission;
      if (view !== generation.current) return;
      update({
        messages: mergeMessages(current.current.messages, [
          reply.user_message,
          reply.assistant_message,
        ]),
        pending: undefined,
        notice: "Reply saved.",
      });
      persist();
    } catch (error) {
      if (view !== generation.current) return;
      const e =
        error instanceof ApiError ? error : new ApiError("Reply unconfirmed.");
      const status =
        (e.code === "provider_error" && e.status === 502) ||
        (e.code === "provider_timeout" && e.status === 504)
          ? "failed"
          : e.code === "request_interrupted" && e.status === 409
            ? "interrupted"
            : undefined;
      if (status) {
        outcomes.current.set(pending.request_id, { status, code: e.code });
        update({
          messages: current.current.messages.map((m) =>
            m.request_id === pending.request_id
              ? { ...m, request_status: status, error_code: e.code }
              : m,
          ),
          notice:
            status === "failed"
              ? `${failureReason(e.code)} Checking saved history before a new attempt.`
              : "The reply was interrupted. You can make a new attempt after history is checked.",
        });
      } else if (e.status === 422 && e.code === "validation") {
        update({ pending: undefined, draft: pending.text, notice: e.message });
        persist();
        return;
      } else if (
        (e.status === 409 && e.code === "conversation_busy") ||
        (e.status === 503 && e.code === "server_busy")
      ) {
        update({
          pendingState: "unaccepted",
          notice:
            "Not accepted: the server is busy. Check reply to retry this same message later.",
        });
        return;
      } else if (e.status === 409 && e.code === "request_id_conflict")
        update({
          notice:
            "Request identity conflict. Check reply to reconcile; a replacement will not be sent automatically.",
        });
      else {
        fail(e);
        if (current.current.missing) return;
        update({ notice: `${e.message} Reply unconfirmed. Use Check reply.` });
      }
      const known = current.current.messages.find(
        (m) => m.request_id === pending.request_id,
      );
      await load(view, known ? known.sequence - 1 : 0);
      if (view !== generation.current) return;
      // A validated terminal response settles this identity even if history contains no new sequence.
      if (status && current.current.ready) {
        update({ pending: undefined });
        reconcile();
      }
    }
  }
  async function send(text = current.current.draft) {
    const s = current.current;
    if (
      s.busy ||
      s.pending ||
      !s.ready ||
      s.missing ||
      !s.dealer ||
      !text.trim() ||
      text.length > 4000
    )
      return;
    const view = generation.current;
    update({ busy: true, notice: "" });
    try {
      const creationId = s.creationId ?? crypto.randomUUID();
      update({ creationId });
      persist();
      const conversation =
        s.conversation ?? (await api.create(s.dealer.id, creationId));
      if (view !== generation.current) return;
      update({ conversation });
      persist();
      const pending = { conversation, request_id: crypto.randomUUID(), text };
      update({
        pending,
        pendingState: "unconfirmed",
        draft: "",
        latestSubmittedRequestId: pending.request_id,
      });
      persist();
      await post(pending, view);
    } catch (error) {
      if (view === generation.current)
        update({
          notice: `Conversation creation was unconfirmed; your text has not been sent. ${error instanceof Error ? error.message : ""} Send again to retry creation.`,
        });
    } finally {
      if (view === generation.current) update({ busy: false });
    }
  }
  async function check() {
    const s = current.current;
    if (s.busy || s.missing) return;
    const view = generation.current;
    update({ busy: true });
    try {
      if (!s.ready && s.cursor !== null) await load(view, s.cursor);
      else if (s.pending) {
        update({ latestSubmittedRequestId: s.pending.request_id });
        await post(
          s.pending,
          view,
          s.pendingState === "accepted" ||
            s.messages.some(
              (m) => m.request_id === s.pending?.request_id && !terminal(m),
            ),
        );
      } else if (s.conversation) await load(view, 0);
      else await initialize(view);
    } finally {
      if (view === generation.current) update({ busy: false });
    }
  }
  function newChat() {
    const s = current.current;
    if (!s.missing && (s.busy || s.pending || !s.ready)) return;
    generation.current++;
    outcomes.current.clear();
    update({
      ...initial(),
      dealer: s.dealer,
      ready: !!s.dealer,
      storageWarning: s.storageWarning,
      draft: s.missing ? (s.pending?.text ?? s.draft) : "",
    });
    persist();
  }
  return {
    ...state,
    send,
    check,
    newChat,
    setDraft: (draft: string) => update({ draft }),
  };
}
