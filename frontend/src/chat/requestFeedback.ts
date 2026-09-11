export function failureReason(code: unknown): string {
  if (code === "provider_timeout")
    return "The AI service took too long to respond.";
  if (code === "provider_error")
    return "The AI service could not complete your reply.";
  if (code === "request_interrupted")
    return "Reply processing was interrupted.";
  return "The reply could not be completed.";
}
