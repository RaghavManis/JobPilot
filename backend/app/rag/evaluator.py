from typing import List, Optional
from backend.app.schemas.rag import Evidence, EvaluationResult
from backend.app.core.logging import logger


class EvidenceEvaluator:
    """Evaluates retrieved evidence to prevent AI hallucinations (No evidence -> No claim)."""

    def __init__(
        self,
        sufficient_threshold: float = 0.75,
        weak_threshold: float = 0.50
    ):
        self.sufficient_threshold = sufficient_threshold
        self.weak_threshold = weak_threshold

    def evaluate(self, query: str, evidence_list: List[Evidence]) -> EvaluationResult:
        """Evaluate evidence quality for a question query."""
        if not evidence_list:
            logger.warning(f"No evidence retrieved for query: '{query}' -> INSUFFICIENT_EVIDENCE")
            return EvaluationResult(
                decision="INSUFFICIENT_EVIDENCE",
                reason=f"No relevant information found in knowledge base for query: '{query}'. Human input required.",
                confidence_score=0.0,
                best_evidence=None
            )

        # Sort evidence by retrieval score descending
        sorted_evidence = sorted(evidence_list, key=lambda e: e.retrieval_score, reverse=True)
        best = sorted_evidence[0]

        if best.retrieval_score >= self.sufficient_threshold:
            logger.info(f"Sufficient evidence found for query '{query}' (score={best.retrieval_score:.2f}) from {best.document_name}")
            return EvaluationResult(
                decision="SUFFICIENT_EVIDENCE",
                reason=f"Strong evidence found in '{best.document_name}' (chunk: {best.chunk_id}, score: {best.retrieval_score:.2f}).",
                confidence_score=best.retrieval_score,
                best_evidence=best
            )

        elif best.retrieval_score >= self.weak_threshold:
            logger.info(f"Weak evidence found for query '{query}' (score={best.retrieval_score:.2f}) -> WEAK_EVIDENCE")
            return EvaluationResult(
                decision="WEAK_EVIDENCE",
                reason=f"Partial or low-confidence match found in '{best.document_name}' (score: {best.retrieval_score:.2f}). Human review recommended.",
                confidence_score=best.retrieval_score,
                best_evidence=best
            )

        else:
            logger.warning(f"Evidence score too low ({best.retrieval_score:.2f}) for query '{query}' -> INSUFFICIENT_EVIDENCE")
            return EvaluationResult(
                decision="INSUFFICIENT_EVIDENCE",
                reason=f"Retrieved information in '{best.document_name}' score ({best.retrieval_score:.2f}) is below confidence threshold ({self.weak_threshold}). Human input required.",
                confidence_score=best.retrieval_score,
                best_evidence=best
            )
