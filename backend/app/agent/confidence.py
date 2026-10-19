from typing import List, Tuple
from backend.app.config.settings import settings
from backend.app.schemas.form import FormField, ConfidenceResult, FieldValue
from backend.app.core.logging import logger

SENSITIVE_KEYWORDS = [
    "salary", "compensation", "expected pay", "relocate", "relocation",
    "criminal", "conviction", "disability", "veteran", "race", "ethnicity",
    "gender", "sponsorship", "visa", "background check"
]


class ConfidenceEngine:
    """Categorizes generated answers into Auto-fill, Suggested Human Review, or Mandatory Human Input."""

    def __init__(
        self,
        auto_threshold: float = None,
        suggest_threshold: float = None
    ):
        self.auto_threshold = auto_threshold or settings.CONFIDENCE_THRESHOLD_AUTO
        self.suggest_threshold = suggest_threshold or settings.CONFIDENCE_THRESHOLD_SUGGEST

    def is_sensitive_question(self, label_or_name: str, result: ConfidenceResult = None) -> bool:
        """Check if a field question touches sensitive personal choices that lack clear profile authorization."""
        if not label_or_name:
            return False
        text_lower = label_or_name.lower()

        # If answer is backed by verified user profile with high confidence,
        # safe to auto-fill without forcing redundant HITL
        if result and result.confidence >= self.auto_threshold and not result.requires_human_input:
            if any(str(c).startswith("profile.") for c in (result.source_citations or [])):
                return False

        return any(keyword in text_lower for keyword in SENSITIVE_KEYWORDS)

    def evaluate_field(
        self,
        field: FormField,
        result: ConfidenceResult
    ) -> str:
        """Return decision category: AUTO_FILL | HUMAN_CONFIRMATION | MANDATORY_HUMAN_INPUT."""
        label = field.label or field.name or ""

        # Sensitive questions or missing evidence always require human input
        if result.requires_human_input or self.is_sensitive_question(label, result):
            logger.info(f"Field '{field.data_jp_id}' ('{label}') marked as MANDATORY_HUMAN_INPUT (Sensitive or explicit flag).")
            return "MANDATORY_HUMAN_INPUT"

        if result.confidence >= self.auto_threshold:
            return "AUTO_FILL"
        elif result.confidence >= self.suggest_threshold:
            return "HUMAN_CONFIRMATION"
        else:
            return "MANDATORY_HUMAN_INPUT"

    def partition_answers(
        self,
        fields: List[FormField],
        answers: List[ConfidenceResult]
    ) -> Tuple[List[FieldValue], List[ConfidenceResult]]:
        """Partition answers into auto_fill queue and human_review queue."""
        field_map = {f.data_jp_id: f for f in fields}
        auto_fill_queue: List[FieldValue] = []
        human_review_queue: List[ConfidenceResult] = []

        for ans in answers:
            field = field_map.get(ans.field_id)
            if field:
                ans.question_text = ans.question_text or field.label or field.name or field.placeholder or ans.field_id
                ans.section_heading = ans.section_heading or field.section_heading
                ans.helper_text = ans.helper_text or field.helper_text
                ans.field_type = ans.field_type or field.input_type or field.tag_name
                ans.options = ans.options or (field.options or [])
                ans.is_required = field.is_required

            if not field or not ans.answer:
                human_review_queue.append(ans)
                continue

            category = self.evaluate_field(field, ans)

            if category == "AUTO_FILL":
                auto_fill_queue.append(FieldValue(
                    data_jp_id=ans.field_id,
                    value=ans.answer,
                    field_type=field.input_type
                ))
            else:
                human_review_queue.append(ans)

        logger.info(f"Confidence partition complete: {len(auto_fill_queue)} auto-fillable, {len(human_review_queue)} requiring human review.")
        return auto_fill_queue, human_review_queue
