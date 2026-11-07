import base64
import io
import pytest
from PIL import Image
from backend.api.services.chat import build_messages, stream_openai_chat, stream_ollama_chat
from backend.core.visual_assets import VisualAssetStore


def test_build_messages_visual_sliding_window_decay(tmp_path, monkeypatch):
    """
    Verify visual context sliding window:
    - Recent turns (< 2 turns ago) retain high-res image payloads.
    - Older turns (>= 2 turns ago) have images stripped and decayed to [历史附图: ... (已阅，已衰减)].
    """
    monkeypatch.setattr("backend.config.settings.UPLOAD_DIR", str(tmp_path))

    # Create dummy images
    img1 = Image.new("RGB", (50, 50), color=(255, 0, 0))
    b1 = io.BytesIO()
    img1.save(b1, format="JPEG")
    p1 = VisualAssetStore.save_visual_asset("doc1", "turn1.jpg", b1.getvalue())

    img2 = Image.new("RGB", (60, 60), color=(0, 255, 0))
    b2 = io.BytesIO()
    img2.save(b2, format="JPEG")
    p2 = VisualAssetStore.save_visual_asset("doc2", "turn2.jpg", b2.getvalue())

    img3 = Image.new("RGB", (70, 70), color=(0, 0, 255))
    b3 = io.BytesIO()
    img3.save(b3, format="JPEG")
    p3 = VisualAssetStore.save_visual_asset("doc3", "turn3.jpg", b3.getvalue())

    # Build 3 turns of history:
    # idx 0: Turn 1 (oldest, dist=2 from latest in history)
    # idx 1: Turn 2 (middle, dist=1)
    # idx 2: Turn 3 (most recent in history, dist=0)
    history = [
        {"role": "user", "content": "Look at turn 1 image", "images": [p1]},
        {"role": "assistant", "content": "I see turn 1 image"},
        {"role": "user", "content": "Look at turn 2 image", "images": [p2]},
        {"role": "assistant", "content": "I see turn 2 image"},
        {"role": "user", "content": "Look at turn 3 image", "images": [p3]},
        {"role": "assistant", "content": "I see turn 3 image"},
    ]

    # Current turn question
    messages = build_messages(
        question="What is this current image?",
        context="Some context",
        history=history,
        current_images=[{"mime_type": "image/jpeg", "data": "curr_b64", "label": "current"}],
    )

    # Total messages: system (0), 6 history (1..6), current user (7)
    assert len(messages) == 8
    system_msg = messages[0]
    hist_turn1_user = messages[1]
    hist_turn2_user = messages[3]
    hist_turn3_user = messages[5]
    curr_user = messages[7]

    # 1. Turn 1 user is >= 2 turns away from latest turn in history (idx 0 vs 5, dist=5)
    # It must have images stripped and decayed text added!
    assert "images" not in hist_turn1_user
    assert "[历史附图: 1 张 (已阅，已衰减)]" in hist_turn1_user["content"]

    # 2. Turn 2 user is dist=3 away, also decayed
    assert "images" not in hist_turn2_user
    assert "[历史附图: 1 张 (已阅，已衰减)]" in hist_turn2_user["content"]

    # 3. Turn 3 user (idx 4) has dist=1, within recent 2 turns!
    # Images must be resolved to dict with data and mime_type
    assert "images" in hist_turn3_user
    assert len(hist_turn3_user["images"]) == 1
    assert "data" in hist_turn3_user["images"][0]
    assert hist_turn3_user["images"][0]["mime_type"] == "image/jpeg"

    # 4. Current user has current_images
    assert "images" in curr_user
    assert curr_user["images"][0]["data"] == "curr_b64"


@pytest.mark.asyncio
async def test_stream_openai_multiturn_images_formatting(monkeypatch):
    """
    Verify OpenAI adapter formats messages so that:
    - Only user turns with images get formatted as parts.
    - Each user turn keeps its OWN images instead of broadcasting to all.
    """
    posted_payload = {}

    class MockResponse:
        status_code = 200
        async def aiter_lines(self):
            yield "data: {\"choices\": [{\"delta\": {\"content\": \"Multi-turn OK\"}}]}"
            yield "data: [DONE]"
        def raise_for_status(self):
            pass

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def stream(self, method, url, json=None, headers=None):
            nonlocal posted_payload
            posted_payload = json
            class StreamCtx:
                async def __aenter__(self):
                    return MockResponse()
                async def __aexit__(self, *args):
                    pass
            return StreamCtx()

    monkeypatch.setattr("backend.config.settings.CHAT_PROVIDER", "openai")
    monkeypatch.setattr("backend.config.settings.CHAT_API_KEY", "test-key")
    monkeypatch.setattr("backend.config.settings.CHAT_API_BASE", "https://api.openai.com/v1")
    monkeypatch.setattr("httpx.AsyncClient", MockClient)

    messages = [
        {"role": "system", "content": "You are assistant"},
        {
            "role": "user",
            "content": "Turn 1 question",
            "images": [{"mime_type": "image/jpeg", "data": "b64_turn1"}],
        },
        {"role": "assistant", "content": "Turn 1 answer"},
        {"role": "user", "content": "Turn 2 question (text only)"},
    ]

    tokens = []
    async for tok in stream_openai_chat(model="Qwen/Qwen3-VL-8B-Instruct", messages=messages):
        tokens.append(tok)

    assert "".join(tokens) == "Multi-turn OK"
    out_msgs = posted_payload.get("messages", [])
    assert len(out_msgs) == 4

    # System msg is plain string
    assert isinstance(out_msgs[0]["content"], str)

    # Turn 1 user msg has parts with b64_turn1
    turn1_content = out_msgs[1]["content"]
    assert isinstance(turn1_content, list)
    assert any(p.get("type") == "image_url" and "b64_turn1" in p["image_url"]["url"] for p in turn1_content)

    # Assistant is plain string
    assert isinstance(out_msgs[2]["content"], str)

    # Turn 2 user msg is TEXT ONLY! It should NOT have b64_turn1 injected into it!
    turn2_content = out_msgs[3]["content"]
    assert isinstance(turn2_content, str)
    assert turn2_content == "Turn 2 question (text only)"


@pytest.mark.asyncio
async def test_stream_ollama_multiturn_images_payload(monkeypatch):
    """
    Verify Ollama adapter passes images array inside messages for vision models.
    """
    posted_payload = {}

    class MockResponse:
        def raise_for_status(self):
            pass
        async def aiter_lines(self):
            yield '{"message": {"content": "Ollama VLM OK"}, "done": true}'

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def stream(self, method, url, json=None):
            nonlocal posted_payload
            posted_payload = json
            class StreamCtx:
                async def __aenter__(self):
                    return MockResponse()
                async def __aexit__(self, *args):
                    pass
            return StreamCtx()

    monkeypatch.setattr("httpx.AsyncClient", MockClient)

    messages = [
        {"role": "system", "content": "System prompt"},
        {
            "role": "user",
            "content": "What is in this picture?",
            "images": [{"mime_type": "image/jpeg", "data": "ollama_b64"}],
        },
    ]

    tokens = []
    async for tok in stream_ollama_chat(model="qwen2-vl:2b", messages=messages):
        tokens.append(tok)

    assert "".join(tokens) == "Ollama VLM OK"
    assert "messages" in posted_payload
    ollama_msgs = posted_payload["messages"]
    assert len(ollama_msgs) == 2
    assert ollama_msgs[1]["role"] == "user"
    assert ollama_msgs[1]["images"] == ["ollama_b64"]
