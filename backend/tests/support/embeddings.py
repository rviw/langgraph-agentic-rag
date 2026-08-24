from langchain_core.embeddings import Embeddings

from app.models.document import EMBEDDING_DIMENSIONS


class DeterministicEmbeddings(Embeddings):
    """Cheap, stable vectors so retrieval tests never call a provider."""

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        for token in text.lower().split():
            vector[hash(token) % EMBEDDING_DIMENSIONS] += 1.0
        # A zero vector has no direction, so cosine distance would be undefined.
        if not any(vector):
            vector[0] = 1.0
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)
