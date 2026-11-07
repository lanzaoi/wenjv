"""
Auto-tagging engine with dynamic vocabulary convergence and rule-based fallback.
"""
from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

import httpx

from backend.api.services.tags import (
    get_user_tags_summary_sync,
    normalize_tags,
)
from backend.config import settings

logger = logging.getLogger(settings.LOGGER_NAME)


def extract_rule_tags(text: str, filename: Optional[str] = None) -> List[str]:
    """Extract tags from YAML frontmatter and inline hashtags."""
    found: List[str] = []
    if not text:
        return found

    # 1. Frontmatter tags: tags: [a, b] or yaml list
    fm_match = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if fm_match:
        fm = fm_match.group(1)
        # Inline bracket style: tags: [foo, bar]
        b_match = re.search(r"tags:\s*\[(.*?)\]", fm, re.IGNORECASE)
        if b_match:
            parts = b_match.group(1).split(",")
            found.extend(parts)
        else:
            # Bullet list style:
            # tags:
            #   - foo
            #   - bar
            l_match = re.search(r"tags:\s*\n((?:\s*-\s*[^\n]+\n?)+)", fm, re.IGNORECASE)
            if l_match:
                for line in l_match.group(1).splitlines():
                    val = re.sub(r"^\s*-\s*", "", line).strip()
                    if val:
                        found.append(val)

    # 2. Inline hashtags: e.g. #python #知识库 (avoid markdown headers like # Header)
    hashtag_pattern = re.compile(r"(?:^|\s)#([\w\u4e00-\u9fa5\-]{2,25})(?=\s|[，。！？,\.!?]|$)")
    for m in hashtag_pattern.finditer(text[:3000]):
        found.append(m.group(1))

    return normalize_tags(found)


def _build_sampling_text(text: str, title: str, max_chars: int = 1500) -> str:
    """Sample title + head + tail of text to bound token usage."""
    t_clean = (text or "").strip()
    if len(t_clean) <= max_chars:
        content_sample = t_clean
    else:
        head_len = int(max_chars * 0.7)
        tail_len = max_chars - head_len
        content_sample = f"{t_clean[:head_len]}\n...\n{t_clean[-tail_len:]}"

    return f"【标题/文件名】: {title or '未命名'}\n【正文摘要】:\n{content_sample}"


async def _call_llm_for_tags(
    sample_text: str,
    user_vocabulary: List[str],
    max_tags: int = 5,
) -> List[str]:
    """Call Chat LLM to suggest 3-5 tags, strictly preferring user_vocabulary."""
    vocab_str = ", ".join(user_vocabulary[:40]) if user_vocabulary else "（暂无历史标签）"

    prompt = (
        f"请阅读以下文档标题与正文摘要，提炼 3 到 {max_tags} 个核心技术/主题/场景分类标签。\n"
        f"当前用户的高频标签池：[{vocab_str}]\n\n"
        f"【严格要求】\n"
        f"1. 语义相近或概念相符时，必须优先原样复用高频标签池中的已有词汇，严禁构造同义冗余新词；\n"
        f"2. 仅在已有标签池完全无法覆盖核心概念时才创建必要新词；\n"
        f"3. 仅输出一个合法 JSON 字符串数组，例如 [\"python\", \"rag\", \"数据库\"]，禁止输出任何分析、解释或 Markdown 代码块前缀！\n\n"
        f"{sample_text}"
    )

    system_instruction = "你是一个严谨的个人知识库自动打标与分类引擎。请输出合法的 JSON 数组。"
    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": prompt},
    ]

    provider = getattr(settings, "CHAT_PROVIDER", "ollama").lower()
    raw_content = ""

    if provider == "openai":
        api_key = getattr(settings, "CHAT_API_KEY", "")
        api_base = getattr(settings, "CHAT_API_BASE", "").rstrip("/")
        if not api_key:
            return []
        url = api_base if api_base.endswith("/chat/completions") else f"{api_base}/chat/completions"
        payload = {
            "model": getattr(settings, "CHAT_MODEL", "") or "gpt-3.5-turbo",
            "messages": messages,
            "temperature": 0.2,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            raw_content = data["choices"][0]["message"]["content"]
    elif provider in ("google", "gemini"):
        api_key = getattr(settings, "CHAT_API_KEY", "")
        if not api_key:
            return []
        model_name = getattr(settings, "CHAT_MODEL", "") or "gemma-4-31b-it"
        if model_name.startswith("models/"):
            model_name = model_name[7:]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": f"{system_instruction}\n\n{prompt}"}]}]
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            parts = data.get("candidates", [])[0].get("content", {}).get("parts", [])
            for p in parts:
                if not p.get("thought"):
                    raw_content = p.get("text", "")
                    break
    else:
        # Ollama
        url = settings.OLLAMA_HOST.rstrip("/") + "/api/chat"
        # Use CHAT_MODEL or fallback to first available
        model_name = getattr(settings, "CHAT_MODEL", "") or "qwen2.5:7b"
        payload = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.2},
        }
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_content = (data.get("message") or {}).get("content", "")

    # Parse JSON array
    raw_content = raw_content.strip()
    # Strip markdown code blocks if model wrapped output in ```json ... ```
    if "```" in raw_content:
        block_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw_content, re.DOTALL)
        if block_match:
            raw_content = block_match.group(1)
        else:
            raw_content = re.sub(r"^```(?:json)?|```$", "", raw_content).strip()

    parsed = json.loads(raw_content)
    if isinstance(parsed, list):
        return [str(x) for x in parsed]
    return []


async def generate_document_tags(
    text: str,
    title: str,
    user_id: int,
    manual_tags: Optional[List[str]] = None,
) -> List[str]:
    """
    Generate combined tags: manual_tags (highest priority) + rule_tags + LLM auto-tags.
    Guaranteed Fail-Open: errors will not throw, returns manual + rule tags.
    """
    combined: List[str] = []
    if manual_tags:
        combined.extend(manual_tags)

    rule_tags = extract_rule_tags(text, filename=title)
    combined.extend(rule_tags)

    if not getattr(settings, "AUTO_TAGGING_ENABLED", True):
        return normalize_tags(combined)

    try:
        # Fetch current user's high-frequency vocabulary
        user_vocab_summary = get_user_tags_summary_sync(user_id, limit=50)
        user_vocab = [item["name"] for item in user_vocab_summary if item.get("name")]

        sample_text = _build_sampling_text(
            text=text,
            title=title,
            max_chars=getattr(settings, "AUTO_TAGGING_SAMPLE_CHARS", 1500),
        )

        max_tags = getattr(settings, "AUTO_TAGGING_MAX_TAGS", 5)
        llm_tags = await _call_llm_for_tags(sample_text, user_vocab, max_tags=max_tags)
        combined.extend(llm_tags)
    except Exception as e:
        logger.warning(f"Auto-tagging failed (fail-open to rule/manual tags): {e}")

    return normalize_tags(combined)
