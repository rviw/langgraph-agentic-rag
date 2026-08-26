import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx
from cohere import ClientV2
from pydantic import SecretStr

RERANK_MODEL = "rerank-v4.0-fast"
RERANK_TIMEOUT_SECONDS = 30.0
RERANK_RESULT_LIMIT = 4


@dataclass(frozen=True, slots=True)
class RerankDocument:
    """The complete input a reranker may see: a position and its text."""

    index: int
    text: str


class DocumentReranker(Protocol):
    def rerank(
        self,
        *,
        query: str,
        documents: Sequence[RerankDocument],
    ) -> list[int]:
        """Return pool positions, most relevant first."""


class CohereReranker:
    """Rerank passages with Cohere, sending only the text being ranked."""

    def __init__(self, *, api_key: SecretStr) -> None:
        self._http_client = httpx.Client(timeout=RERANK_TIMEOUT_SECONDS)
        self._client = ClientV2(
            api_key=api_key.get_secret_value(),
            timeout=RERANK_TIMEOUT_SECONDS,
            max_retries=0,
            httpx_client=self._http_client,
        )

    def rerank(
        self,
        *,
        query: str,
        documents: Sequence[RerankDocument],
    ) -> list[int]:
        if not documents:
            return []

        response = self._client.rerank(
            model=RERANK_MODEL,
            query=query,
            documents=[
                json.dumps(
                    {"index": document.index, "text": document.text},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                for document in documents
            ],
            top_n=min(RERANK_RESULT_LIMIT, len(documents)),
        )
        # Positions index the pool that was sent, so validate before use.
        return [
            result.index
            for result in response.results
            if 0 <= result.index < len(documents)
        ]

    def close(self) -> None:
        self._http_client.close()
