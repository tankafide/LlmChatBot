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

// This hook owns browser recovery state; the server owns saved history/outcomes.
// Pending retains immutable ID + text so a lost response can be reconciled safely.
type Pending = Submission & { conversation: string };
type State = {
  dealer?: Dealer;
  conversation?: string;
  creationId?: string;
  messages: Message[];
  pending?: Pending;
  latestSubmittedRequestId?: string;
  // unconfirmed: admission unknown; unaccepted: explicitly refused; accepted:
  // poll status only. Every state retains the same request ID for recovery.
  pendingState: "unconfirmed" | "unaccepted" | "accepted";
  draft: string;
  // busy guards browser activity. pending can outlive busy after a network failure;
  // ready means history loading finished, so sending can safely consider that history.
  busy: boolean;
  ready: boolean;
  missing: boolean;
  notice: string;
  storageWarning: boolean;
  cursor: number | null;
};
// Return fresh empty controller state with its own messages array; history starts not
// ready.
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
// Return true for completed/failed/interrupted messages, and false for in_progress.
const terminal = (m: Message) => m.request_status !== "in_progress";
// Return a new deduplicated array in server sequence order, preserving terminal status
// over stale active data. Neither input array is mutated.
export function mergeMessages(
  previous: Message[],
  incoming: Message[],
): Message[] {
  // Responses may overlap or arrive out of order. Deduplicate by message ID,
  // retain terminal status over stale in_progress data, and order by server sequence.
  // Map each previous message to an ID/message pair to seed deduplication.
  const map = new Map(previous.map((m) => [m.id, m]));
  for (const m of incoming) {
    const old = map.get(m.id);
    map.set(m.id, old && terminal(old) && !terminal(m) ? old : m);
  }
  // Return a signed sequence difference from the comparator to sort in ascending order.
  return [...map.values()].sort((a, b) => a.sequence - b.sequence);
}
// Manage chat/recovery state and return the UI snapshot plus
// send/check/newChat/setDraft actions. Async actions update state rather than returning
// replies.
export function useConversation() {
  const [state, render] = useState<State>(initial);
  // The ref gives async callbacks current state immediately; React state renders it.
  // update writes both, avoiding stale state captured by an older render.
  const current = useRef(state);
  // A generation identifies this view. New chat/unmount invalidates old callbacks
  // without pretending that the underlying server work was cancelled.
  const generation = useRef(0);
  // Remember terminal statuses even before their messages load, so stale history
  // pages cannot resurrect a request already known to have ended.
  const outcomes = useRef(
    new Map<
      string,
      { status: Message["request_status"]; code: string | null }
    >(),
  );
  const key = `autoassist:${location.origin}:mia-motors`;
  // Merge a state patch into the ref and schedule rendering. Return void; async
  // callbacks immediately see the updated ref.
  function update(patch: Partial<State>) {
    current.current = { ...current.current, ...patch };
    render(current.current);
  }
  // Store recovery IDs and pending text, not authoritative chat history. Reload
  // validates this local data and fetches actual messages from the server.
  // Save or clear local recovery data and return void. Storage errors set
  // storageWarning instead of throwing or claiming data was saved.
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
  // Clear pending only when saved identity and text agree. Also discover active
  // server work from history if local recovery state was lost.
  // Reconcile pending work against loaded messages and persist recovery state. Return
  // void; clear matching terminal work or discover an active server turn.
  function reconcile() {
    const s = current.current;
    const found = s.messages.find(
      // Return true for the admitted user message with this pending request ID.
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
      // The predicate returns true for an active user turn; find yields the message or
      // undefined.
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
  // Turn an error into notice/missing state and return void. A validated not_found
  // marks this conversation missing; no retry occurs here.
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
  // Load at most ten history pages, merging messages and advancing the cursor. Resolve
  // void, including stale-view exits; caught API errors update notices.
  async function load(view: number, after: number) {
    const { dealer, conversation } = current.current;
    if (!dealer || !conversation) return;
    update({ ready: false, cursor: after });
    try {
      // Bound history work per action. Keep sending disabled until the final page
      // allows reconciliation to determine whether server work is still active.
      for (let page = 0; page < 10; page++) {
        const result = await api.history(dealer.id, conversation, after);
        if (view !== generation.current) return;
        update({
          messages: mergeMessages(
            current.current.messages,
            // Return each message with a known terminal outcome overlaid, or return it
            // unchanged.
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
  // Load dealership, restore recovery IDs, and resume history/accepted work. Resolve
  // void; caught errors become notices and the active view busy flag is cleared.
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
            // Return whether this message proves the pending request is already active
            // on the server.
            (m) => m.request_id === pending.request_id && !terminal(m),
          )
        )
          // History proves admission; resume polling without submitting another POST.
          await post(pending, view, true);
      } else update({ ready: true });
    } catch (error) {
      if (view === generation.current) fail(error);
    } finally {
      if (view === generation.current) update({ busy: false });
    }
  }
  // Bootstrap this view and return a cleanup callback that invalidates outstanding
  // work. Server execution is not cancelled by that cleanup.
  useEffect(() => {
    const view = ++generation.current;
    void initialize(view);
    // Invalidate old async callbacks by advancing the generation; return void.
    return () => {
      generation.current++;
    };
    // One bootstrap per view; mutations run only from deliberate actions.
    // eslint does not enable exhaustive-deps: the controller reads its current ref.
  }, []);

  // Resolve to the completed message pair, or undefined for stale views, missing
  // dealer, settled failures, or exhausted polling. Update failure state; API errors
  // reject to post.
  async function poll(pending: Pending, view: number) {
    const dealer = current.current.dealer;
    if (!dealer) return;
    // Finite polling with capped backoff. Exhaustion leaves pending uncertain;
    // Check reply resumes recovery rather than declaring the server turn failed.
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
          // Return terminal metadata updates for this request and unchanged messages
          // for other requests.
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
        // Schedule capped backoff resolution; the executor return is ignored and the
        // awaited promise signals only that the delay ended.
        await new Promise((resolve) =>
          setTimeout(resolve, Math.min(500 * 2 ** attempt, 5000)),
        );
    }
    update({
      notice: "The reply is still unconfirmed. Use Check reply to check again.",
    });
  }

  // Submit or poll the original pending identity, then merge completion or reconcile
  // errors. Resolve void; expected failures update UI state and uncertain work stays
  // pending.
  async function post(pending: Pending, view: number, accepted = false) {
    const dealer = current.current.dealer;
    if (!dealer) return;
    try {
      // Known acceptance skips POST. Otherwise retry the original ID and payload;
      // the backend returns active status or replays the stored terminal outcome.
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
          // Return true for a loaded message from this request so history can re-read
          // its status.
          (m) => m.request_id === pending.request_id,
        );
        // Include the user message again: its status can change without a new sequence.
        // Starting after it would miss a failure/interruption update.
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
          // Return terminal metadata updates for this request and unchanged messages
          // for other requests.
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
        // Return true for a loaded message from this request so history can re-read its
        // status.
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
  // Start a deliberate submission when allowed, creating/recovering its conversation
  // first. Resolve void, including blocked sends; retain retry identity and report
  // errors in state.
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
      // Persist creation identity before the network call to recover the same
      // conversation if creation succeeds but its response is lost.
      const creationId = s.creationId ?? crypto.randomUUID();
      update({ creationId });
      persist();
      const conversation =
        s.conversation ?? (await api.create(s.dealer.id, creationId));
      if (view !== generation.current) return;
      update({ conversation });
      persist();
      // Only a deliberate new send generates a new request ID. Persist it before
      // POST so an uncertain response never requires a duplicate turn.
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
  // Resume pagination, poll accepted work, or retry uncertain/unaccepted work
  // with the original ID. Checking never creates a replacement submission.
  // Resume history or recover the existing pending identity. Resolve void, including
  // blocked checks; always clear busy for the active view. Helpers handle expected API
  // errors.
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
              // Return whether history proves admission of this pending identity,
              // allowing polling only.
              (m) => m.request_id === s.pending?.request_id && !terminal(m),
            ),
        );
      } else if (s.conversation) await load(view, 0);
      else await initialize(view);
    } finally {
      if (view === generation.current) update({ busy: false });
    }
  }
  // Reset the local view when allowed, recovering a missing conversation draft. Return
  // void; do not create or delete a server conversation.
  function newChat() {
    const s = current.current;
    if (!s.missing && (s.busy || s.pending || !s.ready)) return;
    // Invalidate outstanding callbacks before clearing this view. If the server
    // conversation is missing, recover pending text as a draft for a deliberate send.
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
    // Replace composer text and return void; typing does not persist or submit the
    // draft.
    setDraft: (draft: string) => update({ draft }),
  };
}
