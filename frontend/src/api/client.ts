import type { components } from "./generated";
type Schemas = components["schemas"];
export type Message = Schemas["ConversationMessageResponse"];
export type Submission = Schemas["SubmitMessageRequest"];
export type Dealer = Schemas["DealershipResponse"];
type History = Schemas["ConversationHistoryResponse"];
type Reply = Schemas["SubmitMessageResponse"];
export class ApiError extends Error {
  constructor(
    message: string,
    public status = 0,
    public code = "unknown",
  ) {
    super(message);
  }
}
export const record = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null;
export const uuid = (v: unknown): v is string =>
  typeof v === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
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
async function request(path: string, body?: object): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), body ? 135_000 : 15_000);
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
    return value;
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
function malformed(): never {
  throw new ApiError("The server returned an unexpected response.");
}
const base = (dealer: string, conversation: string) =>
  `/dealerships/${dealer}/conversations/${conversation}/messages`;
export const api = {
  async dealership(): Promise<Dealer> {
    const v = await request("/dealerships");
    if (!record(v) || !Array.isArray(v.items)) return malformed();
    const dealer: unknown = v.items.find(
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
  async create(dealer: string): Promise<string> {
    const body: Schemas["CreateConversationRequest"] = {};
    const v = await request(`/dealerships/${dealer}/conversations`, body);
    if (!record(v) || !uuid(v.id)) return malformed();
    return v.id;
  },
  async history(
    dealer: string,
    conversation: string,
    after: number,
  ): Promise<Pick<History, "items" | "next_after_sequence">> {
    const v = await request(
      `${base(dealer, conversation)}?after_sequence=${after}&limit=100`,
    );
    if (
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
    const items = v.items;
    if (
      items.length > 100 ||
      new Set(items.map((m) => m.id)).size !== items.length ||
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
  async send(
    dealer: string,
    conversation: string,
    body: Submission,
  ): Promise<Pick<Reply, "user_message" | "assistant_message">> {
    const v = await request(base(dealer, conversation), body);
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
      assistant.sequence <= user.sequence
    )
      return malformed();
    return { user_message: user, assistant_message: assistant };
  },
};
