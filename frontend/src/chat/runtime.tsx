import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import type { ReactNode } from "react";
import type { Message } from "../api/client";
const convertMessage = (message: Message): ThreadMessageLike => ({
  id: message.id,
  role: message.role,
  content: [{ type: "text", text: message.text }],
  metadata: {
    custom: {
      requestId: message.request_id,
      requestStatus: message.request_status,
      errorCode: message.error_code,
    },
  },
});
export function ChatRuntime({
  messages,
  busy,
  send,
  children,
}: {
  messages: Message[];
  busy: boolean;
  send: (text: string) => Promise<void>;
  children: ReactNode;
}) {
  const runtime = useExternalStoreRuntime({
    messages,
    isRunning: busy,
    convertMessage,
    onNew: async (message) => {
      const part = message.content[0];
      if (part?.type === "text") await send(part.text);
    },
  });
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
