"""
Rule-based role detection for SkillBridge.

This module classifies cleaned job postings into normalized role categories.

It does NOT write to PostgreSQL directly.
It only exposes functions that will later be used by analyze_jobs.py.

Why rule-based here?
- Role categories are limited and stable.
- Job titles usually contain strong role signals.
- The logic is explainable and easy to debug.
- We avoid unnecessary AI/API dependency for simple classification.

AI will be more useful later for skill extraction, where job descriptions
are messy and skills may be written in many different ways.

Allowed role values must match the database constraint chk_detected_role:
- data_analyst
- data_engineer
- bi_analyst
- data_scientist
- machine_learning_engineer
- analytics_engineer
- other
- unknown
"""

from dataclasses import dataclass
import re


ALLOWED_ROLES = {
    "data_analyst",
    "data_engineer",
    "bi_analyst",
    "data_scientist",
    "machine_learning_engineer",
    "analytics_engineer",
    "other",
    "unknown",
}


@dataclass(frozen=True)
class RoleDetectionResult:
    """
    Result returned by role detection.

    detected_role:
        Normalized role category used for analytics.

    role_confidence:
        Simple confidence score between 0 and 1.
        This is not a machine-learning probability.
        It is a rule-quality score.

    role_reason:
        Explanation of why this role was selected.
        Useful for debugging and project presentation.
    """

    detected_role: str
    role_confidence: float
    role_reason: str


def normalize_text(value: str | None) -> str:
    """
    Normalize text before matching.

    Example:
        "  Junior   Data Analyst\\n"
    becomes:
        "junior data analyst"
    """

    if value is None:
        return ""

    text = str(value).lower().strip()
    text = re.sub(r"\s+", " ", text)

    return text


def contains_phrase(text: str, phrase: str) -> bool:
    """
    Check whether a phrase exists in text using word boundaries.

    This avoids some false matches.

    Example:
        phrase = "bi"
        should not match inside "big"

    For multi-word phrases like "data analyst", this works well.
    """

    if not text or not phrase:
        return False

    pattern = r"\b" + re.escape(phrase.lower()) + r"\b"
    return re.search(pattern, text) is not None


def contains_any_phrase(text: str, phrases: list[str]) -> str | None:
    """
    Return the first phrase found in the text.

    Returning the matched phrase lets us create a useful role_reason.
    """

    for phrase in phrases:
        if contains_phrase(text, phrase):
            return phrase

    return None


def build_text_context(
    job_title: str | None,
    description_text: str | None,
    job_function: str | None,
    industries: str | None,
) -> tuple[str, str]:
    """
    Build normalized title text and combined context text.

    We keep title_text separate because title matches are stronger than
    description matches.

    Example:
        Title says "Data Engineer"
        → strong signal

        Description says "collaborate with data engineers"
        → weaker signal
    """

    title_text = normalize_text(job_title)

    context_parts = [
        normalize_text(job_title),
        normalize_text(description_text),
        normalize_text(job_function),
        normalize_text(industries),
    ]

    context_text = " ".join(part for part in context_parts if part)

    return title_text, context_text


def detect_machine_learning_engineer(
    title_text: str,
    context_text: str,
) -> RoleDetectionResult | None:
    """
    Detect machine learning engineering roles.

    This runs before data_engineer because:
        "Machine Learning Engineer"
    contains "engineer", but should not be classified as data_engineer.
    """

    title_phrases = [
        "machine learning engineer",
        "ml engineer",
        "ai engineer",
        "deep learning engineer",
        "computer vision engineer",
        "nlp engineer",
        "machine learning intern",
        "ai intern",
        "ml intern",
    ]

    matched = contains_any_phrase(title_text, title_phrases)
    if matched:
        return RoleDetectionResult(
            detected_role="machine_learning_engineer",
            role_confidence=0.95,
            role_reason=f"Title contains ML engineering phrase: {matched}",
        )

    context_phrases = [
        "machine learning engineering",
        "mlops",
        "model deployment",
        "deploy machine learning models",
        "production machine learning",
        "ml pipelines",
        "deep learning models",
    ]

    matched = contains_any_phrase(context_text, context_phrases)
    if matched:
        return RoleDetectionResult(
            detected_role="machine_learning_engineer",
            role_confidence=0.75,
            role_reason=f"Context contains ML engineering signal: {matched}",
        )

    return None


def detect_analytics_engineer(
    title_text: str,
    context_text: str,
) -> RoleDetectionResult | None:
    """
    Detect analytics engineering roles.

    Analytics engineers usually focus on:
    - dbt
    - warehouse transformations
    - data modeling
    - semantic/analytics layers
    """

    title_phrases = [
        "analytics engineer",
        "analytic engineer",
        "dbt developer",
        "data modeling engineer",
    ]

    matched = contains_any_phrase(title_text, title_phrases)
    if matched:
        return RoleDetectionResult(
            detected_role="analytics_engineer",
            role_confidence=0.95,
            role_reason=f"Title contains analytics engineering phrase: {matched}",
        )

    # Context-only analytics engineering is weaker because dbt/data modeling
    # can also appear in data engineering roles.
    context_phrases = [
        "dbt",
        "data modeling",
        "semantic layer",
        "analytics engineering",
        "warehouse models",
    ]

    matched = contains_any_phrase(context_text, context_phrases)
    if matched and contains_phrase(context_text, "analytics"):
        return RoleDetectionResult(
            detected_role="analytics_engineer",
            role_confidence=0.70,
            role_reason=f"Context suggests analytics engineering: {matched}",
        )

    return None


def detect_data_engineer(
    title_text: str,
    context_text: str,
) -> RoleDetectionResult | None:
    """
    Detect data engineering roles.
    """

    title_phrases = [
        "data engineer",
        "junior data engineer",
        "entry level data engineer",
        "big data engineer",
        "etl engineer",
        "data pipeline engineer",
        "data platform engineer",
        "cloud data engineer",
        "data infrastructure engineer",
    ]

    matched = contains_any_phrase(title_text, title_phrases)
    if matched:
        return RoleDetectionResult(
            detected_role="data_engineer",
            role_confidence=0.95,
            role_reason=f"Title contains data engineering phrase: {matched}",
        )

    context_phrases = [
        "etl pipelines",
        "data pipelines",
        "data warehouse",
        "data warehouses",
        "data lake",
        "spark",
        "airflow",
        "kafka",
        "pipeline orchestration",
    ]

    matched = contains_any_phrase(context_text, context_phrases)
    if matched and contains_phrase(context_text, "engineer"):
        return RoleDetectionResult(
            detected_role="data_engineer",
            role_confidence=0.75,
            role_reason=f"Context contains data engineering signal: {matched}",
        )

    return None


def detect_data_scientist(
    title_text: str,
    context_text: str,
) -> RoleDetectionResult | None:
    """
    Detect data scientist roles.
    """

    title_phrases = [
        "data scientist",
        "junior data scientist",
        "entry level data scientist",
        "product data scientist",
        "decision scientist",
        "research scientist",
        "applied scientist",
    ]

    matched = contains_any_phrase(title_text, title_phrases)
    if matched:
        return RoleDetectionResult(
            detected_role="data_scientist",
            role_confidence=0.95,
            role_reason=f"Title contains data science phrase: {matched}",
        )

    context_phrases = [
        "statistical modeling",
        "predictive modeling",
        "experimentation",
        "a/b testing",
        "machine learning models",
        "causal inference",
        "forecasting models",
    ]

    matched = contains_any_phrase(context_text, context_phrases)
    if matched and contains_phrase(context_text, "data"):
        return RoleDetectionResult(
            detected_role="data_scientist",
            role_confidence=0.70,
            role_reason=f"Context contains data science signal: {matched}",
        )

    return None


def detect_bi_analyst(
    title_text: str,
    context_text: str,
) -> RoleDetectionResult | None:
    """
    Detect BI/reporting/dashboard-heavy roles.

    BI roles are separated from data_analyst because their skill profile
    is often more dashboard/reporting focused:
    - Power BI
    - Tableau
    - dashboards
    - reporting
    - business intelligence
    """

    title_phrases = [
        "business intelligence analyst",
        "bi analyst",
        "business intelligence developer",
        "bi developer",
        "data visualization analyst",
        "reporting analyst",
        "dashboard developer",
        "tableau developer",
        "power bi developer",
        "powerbi developer",
    ]

    matched = contains_any_phrase(title_text, title_phrases)
    if matched:
        return RoleDetectionResult(
            detected_role="bi_analyst",
            role_confidence=0.95,
            role_reason=f"Title contains BI/reporting phrase: {matched}",
        )

    context_phrases = [
        "power bi",
        "powerbi",
        "tableau",
        "dashboard",
        "dashboards",
        "business intelligence",
        "reporting",
        "data visualization",
    ]

    if matched and (
        contains_phrase(title_text, "business intelligence")
        or contains_phrase(title_text, "bi analyst")
        or contains_phrase(title_text, "bi developer")
        or contains_phrase(title_text, "reporting analyst")
        or contains_phrase(title_text, "data visualization")
        or contains_phrase(title_text, "dashboard developer")
        or contains_phrase(title_text, "tableau developer")
        or contains_phrase(title_text, "power bi developer")
        or contains_phrase(title_text, "powerbi developer")
    ):
        return RoleDetectionResult(
            detected_role="bi_analyst",
            role_confidence=0.75,
            role_reason=f"Context contains BI/reporting signal: {matched}",
        )

    return None


def detect_data_analyst(
    title_text: str,
    context_text: str,
) -> RoleDetectionResult | None:
    """
    Detect data analyst roles.

    This is intentionally broad because many student-friendly jobs use titles like:
    - Data Analyst
    - Data Analyst I
    - Junior Data Analyst
    - Analytics Analyst
    - Product Analyst
    """

    title_phrases = [
        "data analyst",
        "junior data analyst",
        "entry level data analyst",
        "data analyst intern",
        "data analytics intern",
        "analytics analyst",
        "product analyst",
        "product data analyst",
        "business data analyst",
        "data quality analyst",
        "data reporting analyst",
        "operations analyst",
        "marketing analyst",
    ]

    matched = contains_any_phrase(title_text, title_phrases)
    if matched:
        return RoleDetectionResult(
            detected_role="data_analyst",
            role_confidence=0.90,
            role_reason=f"Title contains data analyst phrase: {matched}",
        )

    # Softer fallback:
    # Title says analyst/associate, and context contains data-analysis signals.
    analyst_title_signals = [
        "analyst",
        "analytics associate",
        "data associate",
        "reporting associate",
    ]

    data_context_signals = [
        "sql",
        "excel",
        "data analysis",
        "analyze data",
        "dashboards",
        "metrics",
        "reporting",
        "data-driven",
    ]

    matched_title = contains_any_phrase(title_text, analyst_title_signals)
    matched_context = contains_any_phrase(context_text, data_context_signals)

    if matched_title and matched_context:
        return RoleDetectionResult(
            detected_role="data_analyst",
            role_confidence=0.70,
            role_reason=(
                f"Title contains analyst signal: {matched_title}; "
                f"context contains data-analysis signal: {matched_context}"
            ),
        )

    return None


def detect_other_or_unknown(
    title_text: str,
    context_text: str,
) -> RoleDetectionResult:
    """
    Decide between other and unknown.

    other:
        The job is understandable, but it is not one of our target data roles.

    unknown:
        There is not enough information to classify the job.
    """

    if not title_text and not context_text:
        return RoleDetectionResult(
            detected_role="unknown",
            role_confidence=0.00,
            role_reason="No title or context available",
        )

    non_target_title_phrases = [
        "software engineer",
        "frontend developer",
        "front end developer",
        "backend developer",
        "back end developer",
        "full stack developer",
        "project manager",
        "program manager",
        "product manager",
        "account manager",
        "sales",
        "recruiter",
        "human resources",
        "finance manager",
        "marketing manager",
        "customer success",
        "technical writer",
    ]

    matched = contains_any_phrase(title_text, non_target_title_phrases)
    if matched:
        return RoleDetectionResult(
            detected_role="other",
            role_confidence=0.80,
            role_reason=f"Title appears to be non-target role: {matched}",
        )

    # If the title contains some data/analytics signal but no clear role,
    # we keep it unknown instead of forcing a wrong category.
    weak_data_signals = [
        "data",
        "analytics",
        "insights",
        "reporting",
        "business intelligence",
    ]

    matched = contains_any_phrase(title_text, weak_data_signals)
    if matched:
        return RoleDetectionResult(
            detected_role="unknown",
            role_confidence=0.40,
            role_reason=f"Weak data-related title signal but no clear role: {matched}",
        )

    return RoleDetectionResult(
        detected_role="other",
        role_confidence=0.60,
        role_reason="No target data role signal matched",
    )


def validate_role_result(result: RoleDetectionResult) -> RoleDetectionResult:
    """
    Ensure the returned role is allowed by the database constraint.

    This protects us before inserting into PostgreSQL.
    """

    if result.detected_role not in ALLOWED_ROLES:
        raise ValueError(f"Invalid detected_role produced: {result.detected_role}")

    if result.role_confidence < 0 or result.role_confidence > 1:
        raise ValueError(
            f"role_confidence must be between 0 and 1. "
            f"Got: {result.role_confidence}"
        )

    return result


def detect_role(
    job_title: str | None,
    description_text: str | None = None,
    job_function: str | None = None,
    industries: str | None = None,
) -> RoleDetectionResult:
    """
    Detect a normalized role for one job posting.

    Priority matters.

    More specific roles are checked before broader roles.

    Examples:
        "Machine Learning Engineer"
        → machine_learning_engineer, not data_engineer

        "Business Intelligence Analyst"
        → bi_analyst, not data_analyst
    """

    title_text, context_text = build_text_context(
        job_title=job_title,
        description_text=description_text,
        job_function=job_function,
        industries=industries,
    )

    detectors = [
        detect_machine_learning_engineer,
        detect_analytics_engineer,
        detect_data_engineer,
        detect_data_scientist,
        detect_bi_analyst,
        detect_data_analyst,
    ]

    for detector in detectors:
        result = detector(title_text, context_text)

        if result is not None:
            return validate_role_result(result)

    return validate_role_result(
        detect_other_or_unknown(
            title_text=title_text,
            context_text=context_text,
        )
    )


def detect_role_as_dict(
    job_title: str | None,
    description_text: str | None = None,
    job_function: str | None = None,
    industries: str | None = None,
) -> dict[str, str | float]:
    """
    Convenience wrapper for database insertion.

    analyze_jobs.py can use this dictionary directly.
    """

    result = detect_role(
        job_title=job_title,
        description_text=description_text,
        job_function=job_function,
        industries=industries,
    )

    return {
        "detected_role": result.detected_role,
        "role_confidence": result.role_confidence,
        "role_reason": result.role_reason,
    }


def main() -> None:
    """
    Manual test.

    Run:
        docker compose run --rm pipeline python src/enrichment/role_detection.py
    """

    examples = [
        {
            "job_title": "Junior Data Analyst",
            "description_text": "Use SQL, Excel, and dashboards to analyze business metrics.",
        },
        {
            "job_title": "Business Intelligence Analyst",
            "description_text": "Build dashboards using Tableau and Power BI.",
        },
        {
            "job_title": "Data Engineer",
            "description_text": "Build ETL pipelines using Spark and Airflow.",
        },
        {
            "job_title": "Machine Learning Engineer Intern",
            "description_text": "Deploy machine learning models and build ML pipelines.",
        },
        {
            "job_title": "Analytics Engineer",
            "description_text": "Use dbt and data modeling in the warehouse.",
        },
        {
            "job_title": "Data Scientist, Product Analytics",
            "description_text": "Work on experimentation, metrics, and predictive modeling.",
        },
        {
            "job_title": "Strategy & Operations Associate",
            "description_text": "Support business operations and strategic initiatives.",
        },
        {
            "job_title": "Software Engineer",
            "description_text": "Build backend services and APIs.",
        },
    ]

    for example in examples:
        result = detect_role(
            job_title=example["job_title"],
            description_text=example["description_text"],
        )

        print("=" * 70)
        print(f"Title: {example['job_title']}")
        print(f"Detected role: {result.detected_role}")
        print(f"Confidence: {result.role_confidence}")
        print(f"Reason: {result.role_reason}")


if __name__ == "__main__":
    main()