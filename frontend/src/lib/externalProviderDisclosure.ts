export const EXTERNAL_PROVIDER_DISCLOSURE = {
  providers: ["OpenAI", "Cohere", "Tavily", "Langfuse"],
  disclosure:
    "Chat messages and uploaded PDF text may be sent to OpenAI for embedding and answer generation. Search queries and candidate passage text may be sent to Cohere for retrieval reranking. Web search queries may be sent to Tavily. Prompts, outputs, retrieval context, and operational metadata may be recorded in Langfuse for observability.",
  retentionNotice:
    "OpenAI may retain API data for abuse monitoring for up to 30 days. Langfuse retains observability data for its configured plan-default period.",
} as const;
