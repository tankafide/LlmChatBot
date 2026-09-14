import type { components } from "./generated";
// OpenAPI-generated types catch compile-time drift, but network JSON remains
// unknown until these runtime checks validate what the UI actually consumes.
type Schemas = components["schemas"];
export type Message = Schemas["ConversationMessageResponse"];
export type Submission = Schemas["SubmitMessageRequest"];
export type Dealer = Schemas["DealershipResponse"];
type History = Schemas["ConversationHistoryResponse"];
type Reply = Schemas["SubmitMessageResponse"];
export type RequestStatus =
  | Schemas["AcceptedRequestResponse"]
  | (Omit<Schemas["CompletedRequestStatus"], "outcome"> & {
      outcome: Pick<Reply, "user_message" | "assistant_message">;
    })
  | Schemas["FailedRequestStatus"];
// Default status 0 means no validated server outcome. An uncertain transport
// failure is not proof that the server rejected the submission.
export class ApiError extends Error {
  // Initialize ApiError with message and HTTP/domain metadata. new returns the Error
  // instance; defaults represent an unconfirmed outcome.
  constructor(
    message: string,
    public status = 0,
    public code = "unknown",
  ) {
    super(message);
  }
}
// Return whether an unknown value is a non-null object, narrowing its TypeScript type.
// This shallow check does not validate its fields.
export const record = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null;
// Return whether a value is a string matching the UUID shape. This checks syntax, not
// whether that ID exists on the server.
export const uuid = (v: unknown): v is string =>
  typeof v === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
// Return a boolean type guard for the message fields this UI consumes. It validates
// shape but does not establish conversation or payload identity.
function message(v: unknown): v is Message {
  return (
    record(v) &&
    uuid(v.id) &&
    uuid(v.request_id) &&
    Number.isSafeInteger(v.sequence) &&
    Number(v.sequence) > 0 &&
    (v.role === "user" || v.role === "assistant") &&
    typeof v.text === "string" &&
    typeof v.created_at === "string" &&
    ["in_progress", "completed", "failed", "interrupted"].includes(
      String(v.request_status),
    ) &&
    (v.error_code === null || typeof v.error_code === "string")
  );
}
// Send GET or JSON POST and resolve to unknown JSON plus HTTP status. Reject with
// ApiError on HTTP, decoding, timeout, or network failures; always clear the timer.
async function request(
  path: string,
  body?: object,
): Promise<{ value: unknown; status: number }> {
  // Aborting fetch stops browser waiting, not server execution. Recovery reuses
  // the pending request ID because the backend may already have admitted it.
  const controller = new AbortController();
  // The timer callback aborts this browser fetch and returns void; it cannot cancel an
  // already-admitted server turn.
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(`/api${path}`, {
      method: body ? "POST" : "GET",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    let value: unknown;
    try {
      value = await response.json();
    } catch {
      throw new ApiError("The server returned an unreadable response.");
    }
    // Normalize application errors and FastAPI validation responses. Unexpected
    // bodies remain uncertain instead of inventing a terminal turn outcome.
    if (!response.ok) {
      if (
        record(value) &&
        record(value.error) &&
        typeof value.error.code === "string" &&
        typeof value.error.message === "string"
      )
        throw new ApiError(
          value.error.message,
          response.status,
          value.error.code,
        );
      if (
        response.status === 422 &&
        record(value) &&
        Array.isArray(value.detail)
      )
        throw new ApiError(
          "Please edit your message and try again.",
          422,
          "validation",
        );
      throw new ApiError("The server returned an unexpected error.");
    }
    return { value, status: response.status };
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (controller.signal.aborted)
      throw new ApiError(
        "The connection timed out before a response was confirmed. Processing may still be running.",
      );
    throw new ApiError(
      "Could not reach the server or confirm its response. Check your connection; processing may still be running.",
    );
  } finally {
    clearTimeout(timer);
  }
}
// Always throw ApiError for an unexpected response. The never return type means this
// function cannot finish normally.
function malformed(): never {
  throw new ApiError("The server returned an unexpected response.");
}
// Return the message collection path for a dealership/conversation pair; no request is
// sent.
const base = (dealer: string, conversation: string) =>
  `/dealerships/${dealer}/conversations/${conversation}/messages`;
export const api = {
  // Fetch and resolve to the validated Mia Motors dealership record. Reject with
  // ApiError when missing, malformed, or unreachable.
  async dealership(): Promise<Dealer> {
    const { value: v, status } = await request("/dealerships");
    if (status !== 200 || !record(v) || !Array.isArray(v.items))
      return malformed();
    const dealer: unknown = v.items.find(
      // Return true for the configured dealership slug; find returns that item or
      // undefined.
      (item: unknown) => record(item) && item.slug === "mia-motors",
    );
    if (dealer === undefined)
      throw new ApiError(
        "Mia Motors is not configured. Check config/dealerships.json and restart the backend.",
      );
    if (
      !record(dealer) ||
      !uuid(dealer.id) ||
      typeof dealer.name !== "string" ||
      dealer.slug !== "mia-motors"
    )
      return malformed();
    return { id: dealer.id, name: dealer.name, slug: dealer.slug };
  },
  // Create/recover using the supplied creation ID and resolve to the conversation UUID.
  // Reject on invalid or failed responses; callers retain the same ID for retries.
  async create(dealer: string, creationId: string): Promise<string> {
    const body: Schemas["CreateConversationRequest"] = {
      creation_id: creationId,
    };
    const { value: v, status } = await request(
      `/dealerships/${dealer}/conversations`,
      body,
    );
    if (status !== 201 || !record(v) || !uuid(v.id)) return malformed();
    return v.id;
  },
  // Resolve to a validated ordered message page and next cursor (null at the end).
  // Reject malformed pages or failed transport; no browser state is changed here.
  async history(
    dealer: string,
    conversation: string,
    after: number,
  ): Promise<Pick<History, "items" | "next_after_sequence">> {
    const { value: v, status } = await request(
      `${base(dealer, conversation)}?after_sequence=${after}&limit=100`,
    );
    if (
      status !== 200 ||
      !record(v) ||
      v.conversation_id !== conversation ||
      !Array.isArray(v.items) ||
      !v.items.every(message) ||
      !(
        v.next_after_sequence === null ||
        (Number.isSafeInteger(v.next_after_sequence) &&
          Number(v.next_after_sequence) > after)
      )
    )
      return malformed();
    // Validate ordering, unique IDs, and cursor progress as well as field types.
    // Malformed history must not advance recovery or mark loading complete.
    const items = v.items;
    if (
      items.length > 100 ||
      // Project each message to its ID so the Set size detects duplicates; callbacks
      // return strings.
      new Set(items.map((m) => m.id)).size !== items.length ||
      // Return true when a message fails strict sequence progression, invalidating the
      // page.
      items.some((m, i) => m.sequence <= (items[i - 1]?.sequence ?? after)) ||
      (v.next_after_sequence !== null &&
        v.next_after_sequence !== items.at(-1)?.sequence)
    )
      return malformed();
    return {
      items,
      next_after_sequence: v.next_after_sequence as number | null,
    };
  },
  // Submit the supplied immutable ID/text and resolve to acceptance or a validated
  // completed user/assistant pair. Reject errors without inventing a replacement ID.
  async send(
    dealer: string,
    conversation: string,
    body: Submission,
  ): Promise<
    | Schemas["AcceptedRequestResponse"]
    | Pick<Reply, "user_message" | "assistant_message">
  > {
    const { value: v, status } = await request(
      base(dealer, conversation),
      body,
    );
    if (
      status === 202 &&
      record(v) &&
      v.conversation_id === conversation &&
      v.request_id === body.request_id &&
      v.status === "in_progress"
    ) {
      return {
        conversation_id: conversation,
        request_id: body.request_id,
        status: "in_progress",
      };
    }
    // New admission returns 202; a completed same-ID retry can return 200.
    // Validate either outcome before it can settle browser state.
    if (status !== 200) return malformed();
    return reply(v, conversation, body);
  },
  // Resolve to a validated in_progress, completed, failed, or interrupted status for
  // this request. Terminal failure is returned as data; transport/protocol errors
  // reject.
  async status(
    dealer: string,
    conversation: string,
    body: Submission,
  ): Promise<RequestStatus> {
    const { value: v, status } = await request(
      `/dealerships/${dealer}/conversations/${conversation}/requests/${body.request_id}`,
    );
    if (
      status !== 200 ||
      !record(v) ||
      v.conversation_id !== conversation ||
      v.request_id !== body.request_id
    )
      return malformed();
    if (v.status === "in_progress" && v.outcome === undefined)
      return {
        conversation_id: conversation,
        request_id: body.request_id,
        status: "in_progress",
      };
    if (v.status === "completed") {
      return {
        conversation_id: conversation,
        request_id: body.request_id,
        status: "completed",
        outcome: reply(v.outcome, conversation, body),
      };
    }
    if (
      (v.status === "failed" || v.status === "interrupted") &&
      record(v.outcome) &&
      record(v.outcome.error) &&
      typeof v.outcome.error.code === "string" &&
      typeof v.outcome.error.message === "string"
    )
      return {
        conversation_id: conversation,
        request_id: body.request_id,
        status: v.status,
        outcome: {
          error: {
            code: v.outcome.error.code,
            message: v.outcome.error.message,
          },
        },
      };
    return malformed();
  },
};

// Bind completion to the exact conversation, request ID, and submitted text.
// A well-shaped response for another request must not clear this pending turn.
// Validate completion identity and message consistency, then return the user/assistant
// pair. Throw ApiError if any required field, role, sequence, or payload check fails.
function reply(
  v: unknown,
  conversation: string,
  body: Submission,
): Pick<Reply, "user_message" | "assistant_message"> {
  if (
    !record(v) ||
    v.conversation_id !== conversation ||
    v.request_id !== body.request_id ||
    v.status !== "completed" ||
    !message(v.user_message) ||
    !message(v.assistant_message)
  )
    return malformed();
  const user = v.user_message,
    assistant = v.assistant_message;
  if (
    user.role !== "user" ||
    assistant.role !== "assistant" ||
    user.request_id !== body.request_id ||
    assistant.request_id !== body.request_id ||
    user.text !== body.text ||
    user.request_status !== "completed" ||
    assistant.request_status !== "completed" ||
    // Server sequence establishes durable message order, independent of which
    // browser response happened to arrive first.
    assistant.sequence <= user.sequence
  )
    return malformed();
  return { user_message: user, assistant_message: assistant };
}
