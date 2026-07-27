"""Rule-based Query Classifier for RAG dynamic RRF weighting.

Classifies user queries into:
1. "long_question": Contains Chinese question words and length > 8.
2. "short_keyword": Contains alphanumeric model patterns OR length <= 10 without question words.
3. "default": Neither of the above.

Zero external dependencies. Single invocation latency < 1ms.
"""
import re

QUESTION_WORDS = (
    "什么", "怎么", "为什么", "如何", "哪", "吗", "呢", "吧",
    "?", "？", "怎", "何时", "何地", "谁", "为啥", "是否"
)
MODEL_PATTERN = re.compile(r"(?:[a-zA-Z]+[-\s]?\d+|\d+[-\s]?[a-zA-Z]+)")


def classify(query_text: str) -> str:
    """Classify query text into 'long_question', 'short_keyword', or 'default'.
    
    Priority from high to low:
    1. long_question: Contains Chinese question words and > 8 chars.
    2. short_keyword: Contains alphanumeric model patterns OR <= 10 chars without question words.
    3. default: All other queries.
    """
    if not query_text:
        return "default"

    text = query_text.strip()
    length = len(text)
    has_question_word = any(qw in text for qw in QUESTION_WORDS)

    # 1. long_question
    if has_question_word and length > 8:
        return "long_question"

    # 2. short_keyword
    if MODEL_PATTERN.search(text) or (length <= 10 and not has_question_word):
        return "short_keyword"

    # 3. default
    return "default"
