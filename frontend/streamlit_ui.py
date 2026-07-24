import streamlit as st
import ollama
import asyncio
from typing import AsyncGenerator
import time
import PyPDF2
import json
import re
import base64
import aiohttp
import math
from datetime import datetime
from frontend.utils import (
    save_token_to_storage,
    navigate_to,
    upload_file_to_api_server,
    submit_link,
    submit_bulk_links,
    submit_recursive_crawl_link,
    fetch_documents,
    fetch_chat_models,
    stream_backend_chat,
    citations_to_docs,
    upload_note_to_api_server,
    fetch_notes,
    fetch_file,
    fetch_files,
    update_note_to_api_server,
    fetch_links,
    fetch_file_status,
    delete_note,
    delete_link,
    delete_file,
    sync_notes
)

from frontend.config import settings
from frontend.streamlit_component.easymde import easy_mde

SVG_ICON = """
<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
   <rect x="10" y="75" width="75" height="15"
                  stroke="#666"
                  stroke-width="2"
                  fill="#f5f5f5"/>

   <!-- Left-side books -->
   <rect x="15" y="30" width="10" height="45"
         stroke="#666"
         stroke-width="2"
         fill="#e6e6fa"/>
   <rect x="30" y="35" width="10" height="40"
         stroke="#666"
         stroke-width="2"
         fill="#e6ffe6"/>

   <!-- Boy character -->
   <circle cx="58" cy="55" r="8"
           stroke="#333"
           stroke-width="2"
           fill="#ffcccb"/>

   <!-- Body and arm reaching toward books -->
   <line x1="58" y1="63" x2="58" y2="75"
         stroke="#333"
         stroke-width="2"/>
   <path d="M58,68 Q48,65 43,70"
         stroke="#333"
         stroke-width="2"
         fill="none"/>

</svg>
"""

TIPS = """
### 提示词快捷指令（用于在特定分类中精确检索）

* `/notes 搜索词`

* `/files 搜索词`

* `/links 搜索词`

### 列表快捷指令

* `/notes-list`

* `/links-list`

* `/files-list`

### 手动同步笔记

当您使用其他外部编辑器直接修改笔记文件时，此功能非常有用：

* `/notes-sync`
"""


class OllamaChatApp:
    def __init__(self):
        self.init_session_state()
        self.setup_streamlit_page_layout()

    def init_session_state(self):
        if "authenticated" not in st.session_state:
            st.session_state.authenticated = False
        if "username" not in st.session_state:
            st.session_state.username = None
        if "token" not in st.session_state:
            st.session_state.token = None
        if "current_page" not in st.session_state:
            st.session_state.current_page = "login"
            
        if 'messages' not in st.session_state:
            st.session_state.messages = []
        if 'is_generating' not in st.session_state:
            st.session_state.is_generating = False
        if 'file_uploaded' not in st.session_state:
            st.session_state.file_uploaded = False
        if 'context_window_size' not in st.session_state:
            st.session_state.context_window_size = 10
        if "exclude_selected" not in st.session_state:
            st.session_state.exclude_selected = []
        if "include_selected" not in st.session_state:
            st.session_state.include_selected = []
        if "ollama_model" not in st.session_state:
            st.session_state.ollama_model = None
        if "source_type" not in st.session_state:
            st.session_state.source_type = None
        if "ollama_model_selected" not in st.session_state:
            st.session_state.ollama_model_selected = None
        if "view_mode" not in st.session_state:
            st.session_state.view_mode = None
        if 'list_page_number' not in st.session_state:
            st.session_state.list_page_number = 1
        if 'list_page_number_modified' not in st.session_state:
            st.session_state.list_page_number_modified = False
        if 'edit_note_url' not in st.session_state:
            st.session_state.edit_note_url = None
        if 'prompt_with_docs' not in st.session_state:
            st.session_state.prompt_with_docs = {}
        if 'right_sidebar_rendered' not in st.session_state:
            st.session_state.right_sidebar_rendered = False
        if 'discussion_mode' not in st.session_state:
            st.session_state.discussion_mode = "context-aware"
        if 'updated_note_content' not in st.session_state:
            st.session_state.updated_note_content = None

    def setup_streamlit_page_layout(self):
        self.qna_tab = st
        self.main_content, self.right_sidebar = self.qna_tab.columns([3, 1])

    def format_chat_history(self):
        """Format the entire chat history for context"""
        formatted_messages = []

        # Add system message first
        formatted_messages.append({
            "role": "system",
            "content": '你是一个文档问答助手。请仅根据提供的上下文内容回答问题。如果在上下文中找不到答案，请直接说明。'
        })

        # Add all previous messages
        formatted_messages.extend(st.session_state.messages)

        return formatted_messages

    def format_chat_history_unfocused(self):
        """Format the entire chat history for context"""
        formatted_messages = []

        # Add system message first
        formatted_messages.append({
            "role": "system",
            "content": '你是一个文档问答助手。'
        })

        # Add all previous messages
        formatted_messages.extend(st.session_state.messages)

        return formatted_messages

    def process_uploaded_file_with_links(self, uploaded_file):
        """Process uploaded file, extact links, fetch pages and store in vector database"""
        if uploaded_file is not None:
            try:
                # Extract text based on file type
                if uploaded_file.type == "application/pdf":
                    text_content = self.extract_text_from_pdf(uploaded_file)
                else:  # text file
                    text_content = uploaded_file.read().decode('utf-8')

                if not text_content:
                    st.error("未能从该文件中提取出任何文本内容。")
                    return False

                links = re.findall(
                    r'(https?://[^"\'\s\n]+)(?:["\'\s\n]|$)', text_content)
                filtered_links = list(filter(lambda link: not (
                    link.endswith("svg") or link.endswith("ico") or link.endswith("png")), links))

                chunk_size = 500
                chunked_urls = [
                    filtered_links[i:i + chunk_size]
                    for i in range(0, len(filtered_links), chunk_size)
                ]

                for batch in chunked_urls:
                    submit_bulk_links(batch, settings.DEFAULT_HEADERS)
                return True
            except Exception as e:
                st.error(f"处理文件时出错: {str(e)}")
                return False
        return False

    def process_uploaded_file(self, uploaded_file):
        if uploaded_file is not None:
            try:
                submitted, filename = upload_file_to_api_server(uploaded_file)
                if submitted:
                    st.success(
                        f"文件: {uploaded_file.name} 已提交处理")

                processed = False
                file_status = "pending"
                for i in range(100):
                    time.sleep(5)
                    _, status = fetch_file_status(filename)
                    if status == "finished":
                        processed = True
                        break
                    else:
                        file_status = status
                return file_status, processed
            except Exception as e:
                st.error(f"处理文件时出错: {str(e)}")
                return "error", False
        return "error", False

    def extract_text_from_pdf(self, pdf_file):
        """Extract text from PDF file"""
        try:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text()
            return text
        except Exception as e:
            st.error(f"从 PDF 提取文本时出错: {str(e)}")
            return None

    def create_prompt_with_context(self, query: str, context: str) -> str:
        """Create a focused prompt that instructs the model to use only the provided context"""
        return f"""请仅根据提供的上下文内容回答问题。如果上下文中没有包含足够的信息来回答该问题，请回复“我无法根据提供的上下文回答该问题”。

Context: {context}

Question: {query}

Answer: """

    def create_prompt_without_context(self, query: str) -> str:
        """Create a focused prompt that instructs the model to use only the provided context"""
        return f"""请回答以下问题:

Question: {query}

Answer: """

    async def get_llm_response(self, prompt: str, context: str = None, context_aware: bool = True) -> AsyncGenerator[str, None]:
        """Get streaming response from LLM  model"""
        try:
            client = ollama.AsyncClient(host=settings.OLLAMA_HOST)

            # Create system message to enforce context-based answering
            system_message_focused = {
                'role': 'system',
                'content': '你是一个文档问答助手。请仅根据提供的上下文内容回答问题。如果在上下文中找不到答案，请直接说明。'
            }
            system_message_non_focused = {
                'role': 'system',
                'content': '你是一个问答助手'
            }

            # Create the focused prompt
            if context_aware:
                focused_prompt = self.create_prompt_with_context(
                    prompt, context)
            else:
                non_focused_prompt = self.create_prompt_without_context(prompt)

            if len(st.session_state.messages) > 1 and context_aware:
                messages = self.format_chat_history()
                messages.append({'role': 'user', 'content': focused_prompt})
            elif len(st.session_state.messages) > 1 and not context_aware:
                messages = self.format_chat_history_unfocused()
                messages.append(
                    {'role': 'user', 'content': non_focused_prompt})
            elif context_aware:
                messages = [
                    system_message_focused,
                    {'role': 'user', 'content': focused_prompt}
                ]
            else:
                messages = [
                    system_message_non_focused,
                    {'role': 'user', 'content': non_focused_prompt}
                ]

            stream = await client.chat(
                model=st.session_state.ollama_model_selected,
                messages=messages,
                stream=True
            )

            async for chunk in stream:
                if not st.session_state.is_generating:
                    break
                if 'message' in chunk:
                    content = chunk['message'].get('content', '')
                    if content:
                        yield content
                        await asyncio.sleep(0)

        except Exception as e:
            yield f"\nError: {str(e)}"

    def display_chat_history(self):
        """Display chat messages from history"""
        for message in st.session_state.messages:
            with self.main_content.chat_message(message["role"]):
                st.markdown(message["content"])

    def ollama_model_selected(self):
        st.session_state.ollama_model_selected = st.session_state.select_ollama_model

    def handle_selection_change(self, source, key):
        """Callback function to handle selection changes"""
        # Store the selection in session state
        value = st.session_state[key]
        st.session_state.right_sidebar_rendered = False
        if value == "Include":
            st.session_state.include_selected.append(source)
        else:
            st.session_state.exclude_selected.append(source)

    def display_references(self, index=0):
        docs = st.session_state.prompt_with_docs.get("docs", [])

        if st.session_state.discussion_mode in ["context-aware", "only-links"] and docs:
            context = "\n\n".join(
                [doc["page_content"] for doc in docs])
            # Prepare references for sidebar
            references = []

            for doc in docs:
                metadata = doc["metadata"]
                source = metadata.get("source", "N/A")
                reference = {
                    "source": source,
                    "page": metadata.get("page", "N/A"),
                    "score": doc["score"],
                    "text": doc["page_content"],
                    "title": metadata.get("title", source),
                    "filename": metadata.get("filename", ""),
                    "source_type": metadata.get("source_type", "")
                }
                references.append(reference)

            # index field is used for controlling
            # where to display the references
            if index == 2:
                ref = self.main_content
            else:
                ref = self.right_sidebar
            with ref:
                if st.session_state.include_selected:
                    st.info(
                        f"已包含引用: {','.join(st.session_state.include_selected)}", icon="ℹ️")
                if st.session_state.exclude_selected:
                    st.info(
                        f"已排除引用: {','.join(st.session_state.exclude_selected)}", icon="ℹ️")

                for i, ref in enumerate(references, 1):
                    if ref["filename"]:
                        src = ref['filename']
                    else:
                        src = ref['source']
                    if index == 2:
                        expand = True
                    elif st.session_state.discussion_mode == "only-links":
                        # It means, discussion mode is show only links
                        # but the references will load on right sidebar
                        # so we don't want to auto expand them
                        expand = False
                    else:
                        expand = (i == 1)
                    with st.expander(
                        f"引用 {i} (得分: {ref['score']:.2f}, 页码: {ref['page']})",
                        expanded=expand
                    ):
                        st.session_state.right_sidebar_rendered = True
                        st.radio(
                            src,
                            options=["Include", "Exclude"],  # Keeping English for logic value unless logic is changed
                            key=f"radio_{index}_{i}",
                            horizontal=True,
                            index=None,
                            on_change=self.handle_selection_change,
                            args=(ref['source'], f"radio_{index}_{i}",)
                        )
                        if ref['text']:
                            txt = re.sub(r'\n+', '\n', ref['text'])
                            st.markdown(txt[:500])
                        if ref['filename']:

                            cols = st.columns([5, 3])
                            cols[0].button(
                                "查看文档",
                                key=f"btn_{index}_{i}",
                                on_click=self.render_file_sync,
                                args=(ref['source'], ref['page'],)
                            )
                            if ref['source_type'] == "note":
                                cols[1].button(
                                    "编辑",
                                    key=f"edit_note_button_{index}_{i}",
                                    on_click=self.edit_note_btn_clicked,
                                    args=(ref['source'],)
                                )

    def format_resource_list(self, docs):
        formatted_text = ""
        for i, resource in enumerate(docs):
            metadata = resource.get("metadata")
            source_type = metadata.get("source_type")
            title = metadata.get("title", "No Title")
            url = "#"
            if source_type == "link":
                url = metadata.get("source", "#")

            text = resource.get("page_content", "无可用描述")

            # Format each item with markdown
            formatted_text += f"#### {i+1} [{title}]({url})\n"
            formatted_text += f"{text}\n\n---\n"

        return formatted_text

    async def process_response(self, docs, prompt: str):

        discussion_mode = st.session_state.discussion_mode
        context = None

        if docs:
            context = "\n\n".join(
                [doc["page_content"] for doc in docs])

        with self.main_content.chat_message("assistant"):
            message_placeholder = st.empty()
            self.qna_tab.container().empty()
            full_response = ""

            if discussion_mode == "only-links":
                message_placeholder.markdown(
                    f"找到的总引用数: {len(docs)}")
                self.display_references(2)
            else:
                # Prefer backend /chat SSE (retrieve+generate on BE).
                # Falls back to direct Ollama only if backend path fails hard.
                use_rag = discussion_mode == "context-aware"
                history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages[:-1]
                    if m.get("role") in ("user", "assistant")
                ][-8:]
                try:
                    got_token = False
                    async for response_chunk in self.stream_via_backend(
                        prompt, use_rag=use_rag, history=history
                    ):
                        got_token = True
                        full_response += response_chunk
                        message_placeholder.markdown(full_response + "▌")
                        time.sleep(0.01)
                    # context-aware with zero hits: backend still may answer empty-context
                    if (
                        use_rag
                        and not got_token
                        and not st.session_state.prompt_with_docs.get("docs")
                    ):
                        full_response = (
                            "我无法在知识库中找到相关信息来回答您的问题。"
                        )
                except Exception as e:
                    # Legacy direct-Ollama fallback (needs prefetched docs/context)
                    if use_rag and not docs:
                        docs = fetch_documents(prompt)
                        st.session_state.prompt_with_docs["docs"] = docs
                        context = "\n\n".join(
                            [d["page_content"] for d in docs]
                        ) if docs else None
                    if use_rag and not context:
                        full_response = (
                            "我无法在上传的文档中找到相关信息来回答您的问题。"
                        )
                    else:
                        context_aware = discussion_mode == "context-aware"
                        async for response_chunk in self.get_llm_response(
                            prompt, context, context_aware
                        ):
                            full_response += response_chunk
                            message_placeholder.markdown(full_response + "▌")
                            time.sleep(0.01)
                        if not full_response:
                            full_response = f"Error: {e}"

                message_placeholder.markdown(full_response)

            st.session_state.messages.append(
                {"role": "assistant", "content": full_response})

    async def stream_via_backend(self, prompt: str, use_rag: bool = True, history=None):
        """Consume POST /chat SSE; update sidebar docs from citations event."""
        import queue
        import threading

        model = st.session_state.ollama_model_selected
        q: queue.Queue = queue.Queue()

        # Extract session state variables securely in main thread to avoid Streamlit thread-context errors
        token = st.session_state.get('token')
        context_window_size = st.session_state.get("context_window_size", 5)
        include_selected = st.session_state.get("include_selected")
        exclude_selected = st.session_state.get("exclude_selected")
        source_type = st.session_state.get("source_type")

        def _producer():
            try:
                for event in stream_backend_chat(
                    prompt,
                    model=model,
                    use_rag=use_rag,
                    history=history or [],
                    token=token,
                    context_window_size=context_window_size,
                    include_selected=include_selected,
                    exclude_selected=exclude_selected,
                    source_type=source_type,
                ):
                    q.put(event)
            except Exception as e:
                q.put({"type": "error", "message": str(e)})
            finally:
                q.put(None)

        threading.Thread(target=_producer, daemon=True).start()

        while True:
            if not st.session_state.is_generating:
                break
            event = await asyncio.to_thread(q.get)
            if event is None:
                break
            et = event.get("type")
            if et == "citations":
                docs = citations_to_docs(event.get("citations"))
                st.session_state.prompt_with_docs["docs"] = docs
            elif et == "token":
                yield event.get("content") or ""
            elif et == "error":
                yield f"\nError: {event.get('message', 'chat failed')}"
            elif et == "done":
                break

    def render_file_sync(self, file_url, page_number=1):
        # when this even is fired, somehow
        # right sidebar content vanishes.
        # To prevent this setting this variable to False
        # meaning right sidebar has vanished.
        # In run() we use this variable to render sidebar again
        # if it has vanished
        st.session_state.right_sidebar_rendered = False
        with self.main_content:
            with st.spinner("正在加载文档..."):
                st.session_state.is_generating = False

                asyncio.run(self.render_file_async(file_url, page_number))

    def render_note_sync(self, file_url, note_id, note_filename):
        with self.main_content:
            with st.spinner("正在加载文档..."):
                st.session_state.is_generating = False
                asyncio.run(self.render_file_async(file_url))

    async def render_file_async(self, file_url, page_number=1):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{settings.API_URL}{file_url}",
                headers={"Authorization": f"Bearer {st.session_state.get('token')}"}
            ) as response:
                if response.status != 200:
                    self.qna_tab.error(
                        f"获取文件失败: {response.status}")
                    return

                content_type = response.headers.get("content-type", "")
                content = await response.read()

                if content_type == "application/pdf":
                    base64_pdf = base64.b64encode(content).decode('utf-8')
                    pdf_display = f'<embed src="data:application/pdf;base64,{base64_pdf}#page={page_number}" width="100%" height="800" type="application/pdf">'
                    self.qna_tab.container(border=True).markdown(
                        pdf_display, unsafe_allow_html=True)
                elif content_type.startswith("image/"):
                    self.qna_tab.container(border=True).image(content)

                elif content_type in ["application/x-sh", "text/markdown"]:
                    try:

                        markdown_text = content.decode(
                            'utf-8', errors='replace')
                        self.qna_tab.container(border=True).markdown(
                            markdown_text, unsafe_allow_html=True)

                    except:
                        self.qna_tab.text_area(
                            "Markdown Content", content, height=300)

                elif content_type == "application/json":
                    try:
                        text = content.decode('utf-8', errors='replace')
                        self.qna_tab.container(border=True).json(text)
                    except:
                        self.qna_tab.text_area(
                            "JSON Content", content, height=300)

                elif content_type.startswith("text/"):
                    try:
                        text = content.decode('utf-8', errors='replace')
                        self.qna_tab.container(border=True).markdown(text)
                    except Exception as e:
                        self.qna_tab.error(f"渲染文本文件失败: {e}")

                else:
                    self.qna_tab.warning(
                        f"不支持的文件类型: {content_type}")

    def get_ollama_models(self):
        # Prefer backend proxy so FE does not need direct Ollama access
        models = fetch_chat_models()
        if models:
            return models
        try:
            client = ollama.Client(host=settings.OLLAMA_HOST)
            models = [i.model for i in client.list().models]
            return models
        except Exception as e:
            st.error(f"连接 Ollama 出错: {str(e)}")
            return []

    def set_source_type(self, prompt):
        if prompt.startswith("/links"):
            st.session_state.source_type = "link"
            prompt = re.sub(r"^/links ", "", prompt)
        elif prompt.startswith("/notes"):
            st.session_state.source_type = "note"
            prompt = re.sub(r"^/notes ", "", prompt)
        elif prompt.startswith("/files"):
            st.session_state.source_type = "file"
            prompt = re.sub(r"^/files ", "", prompt)

        return prompt

    def set_source_type_radio_button(self, key):
        value = st.session_state.get(key, "")
        if value.startswith("/links"):
            st.session_state.source_type = "link"
        elif value.startswith("/notes"):
            st.session_state.source_type = "note"
        elif value.startswith("/files"):
            st.session_state.source_type = "file"
        else:
            st.session_state.source_type = None

        return value

    def format_timestamp(self, timestamp_str):
        if timestamp_str is None:
            return "文件仍在处理中"
        # Parse the ISO format timestamp
        dt = datetime.fromisoformat(timestamp_str)

        # Get the day and add the appropriate ordinal suffix
        day = dt.day
        if 4 <= day <= 20 or 24 <= day <= 30:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

        # Format the datetime with the day suffix
        formatted_date = dt.strftime(f"%-d{suffix} %B %Y %-I:%M %p")

        return formatted_date

    def display_files(self):

        page_size = settings.LIST_PAGE_SIZE

        # Initialize session state for page number if not exists
        current_page = st.session_state.list_page_number

        # Calculate offset for API call
        offset = (current_page - 1) * page_size

        # Fetch only the notes for the current page
        response = fetch_files(offset, page_size)
        records = response["files"]
        total_files = response["total"]

        total_pages = math.ceil(total_files / page_size)

        # Edge case where notes are still not created
        # but we are trying to list notes
        if total_pages == 0:
            total_pages = 1

        col1, col2 = self.main_content.columns([5, 2])

        with col1:
            # Show current range of notes being displayed
            start_idx = offset + 1
            end_idx = min(offset + page_size, total_files)
            st.write(f"显示文件 {start_idx}-{end_idx}，共 {total_files} 个")

        with col2:
            # Simple page input
            page_input = st.number_input(
                "前往页码",
                min_value=1,
                max_value=total_pages,
                value=current_page,
                step=1,
                key="page_input"
            )

        # Update page number when input changes
        if page_input != current_page:
            st.session_state.list_page_number = page_input
            st.session_state.list_page_number_modified = True
            st.rerun()

        header_cols = self.main_content.columns([1, 5, 5, 2, 2])
        header_cols[0].write("**编号**")
        header_cols[1].write("**标题**")
        header_cols[2].write("**更新时间**")
        header_cols[3].write("**操作**")

        # Add a separator
        self.main_content.markdown("---")

        # Display each uploaded file
        for i, record in enumerate(records):
            cols = self.main_content.columns([1, 5, 5, 2, 2])

            # Display ID
            cols[0].write(f"{i+offset+1}")

            # Display Title
            title = record["filename"]
            cols[1].write(title)

            url = record["file_url"]

            updated_at = self.format_timestamp(record["updated_at"])
            cols[2].write(updated_at)

            cols[3].button(
                "查看",
                key=f"view_file_{i+offset+1}",
                on_click=self.render_file_sync,
                args=(url,))

            delete_key = f"delete_file_{i+offset+1}",
            cols[4].button(
                "删除",
                key=delete_key,
                on_click=self.delete_file_btn_clicked,
                args=(title, )
            )

    def display_notes(self):
        page_size = settings.LIST_PAGE_SIZE

        # Initialize session state for page number if not exists
        current_page = st.session_state.list_page_number

        # Calculate offset for API call
        offset = (current_page - 1) * page_size

        # Fetch only the notes for the current page
        response = fetch_notes(offset, page_size)
        records = response["notes"]
        total_notes = response["total"]

        total_pages = math.ceil(total_notes / page_size)

        # Edge case where notes are still not created
        # but we are trying to list notes
        if total_pages == 0:
            total_pages = 1

        col1, col2 = self.main_content.columns([5, 2])

        with col1:
            # Show current range of notes being displayed
            start_idx = offset + 1
            end_idx = min(offset + page_size, total_notes)
            st.write(f"显示笔记 {start_idx}-{end_idx}，共 {total_notes} 篇")

        with col2:
            # Simple page input
            page_input = st.number_input(
                "前往页码",
                min_value=1,
                max_value=total_pages,
                value=current_page,
                step=1,
                key="page_input"
            )

        # Update page number when input changes
        if page_input != current_page:
            st.session_state.list_page_number = page_input
            st.session_state.list_page_number_modified = True
            st.rerun()

        header_cols = self.main_content.columns([1, 5, 5, 2, 2, 2])
        header_cols[0].write("**编号**")
        header_cols[1].write("**标题**")
        header_cols[2].write("**更新时间**")
        header_cols[3].write("**操作**")

        # Add a separator
        self.main_content.markdown("---")

        # Display each note
        for i, note in enumerate(records):
            cols = self.main_content.columns([1, 5, 5, 2, 2, 2])

            # Display ID
            cols[0].write(f"{i+offset+1}")

            # Display Title
            title = note["title"]
            cols[1].write(title)

            # filename = note["filename"].replace("-", " ")
            # cols[2].write(filename)

            url = note["url"]
            # View button

            updated_at = self.format_timestamp(note["updated_at"])
            cols[2].write(updated_at)

            cols[3].button(
                "查看",
                key=f"view_note_{note['id']}",
                on_click=self.render_note_sync,
                args=(url, note["id"], note["filename"]))

            cols[4].button(
                "编辑",
                key=f"edit_note_button_{note['id']}",
                on_click=self.edit_note_btn_clicked,
                args=(url,)
            )

            cols[5].button(
                "删除",
                key=f"delete_note_button_{note['id']}",
                on_click=self.delete_note_btn_clicked,
                args=(note["filename"],)
            )

    def display_links(self):

        page_size = settings.LIST_PAGE_SIZE

        # Initialize session state for page number if not exists
        current_page = st.session_state.list_page_number

        # Calculate offset for API call
        offset = (current_page - 1) * page_size

        # Fetch only the notes for the current page
        response = fetch_links(offset, page_size)
        records = response["links"]
        total_links = response["total"]

        total_pages = math.ceil(total_links / page_size)

        # Edge case where links are still not created
        # but we are trying to list links
        if total_pages == 0:
            total_pages = 1

        col1, col2 = self.main_content.columns([5, 2])

        with col1:
            # Show current range of notes being displayed
            start_idx = offset + 1
            end_idx = min(offset + page_size, total_links)
            st.write(f"显示链接 {start_idx}-{end_idx}，共 {total_links} 个")

        with col2:
            # Simple page input
            page_input = st.number_input(
                "前往页码",
                min_value=1,
                max_value=total_pages,
                value=current_page,
                step=1,
                key="page_input"
            )

        # Update page number when input changes
        if page_input != current_page:
            st.session_state.list_page_number = page_input
            st.session_state.list_page_number_modified = True
            st.rerun()

        header_cols = self.main_content.columns([1, 5, 5, 10, 3])
        header_cols[0].write("**编号**")
        header_cols[1].write("**标题**")
        header_cols[2].write("**更新时间**")
        header_cols[3].write("**链接**")
        header_cols[4].write("**操作**")

        # Add a separator
        self.main_content.markdown("---")

        # Display each note
        for i, link in enumerate(records):
            cols = self.main_content.columns([1, 5, 5, 10, 3])

            # Display ID
            cols[0].write(f"{i+offset+1}")

            # Display Title
            title = link["title"]
            cols[1].write(title)

            url = link["url"]
            # View button

            updated_at = self.format_timestamp(link["updated_at"])
            cols[2].write(updated_at)

            cols[3].write(url)

            cols[4].button(
                "删除",
                key=f"delete_link_button_{i+offset+1}",
                on_click=self.delete_link_btn_clicked,
                args=(link["id"], link["title"], )
            )

    def edit_note_btn_clicked(self, file_url):
        st.session_state.view_mode = "edit-note"
        st.session_state.edit_note_url = file_url
        st.session_state.right_sidebar_rendered = False

    @st.dialog("确认")
    def delete_file_btn_clicked(self, filename):
        st.write(f"您确定要删除 {filename} 吗？")
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("是", key=f"{filename}_confirm_yes", use_container_width=True):
                resp, status = delete_file(filename)
                if status == "deleted":
                    st.rerun()
        with col2:
            if st.button("否", key=f"{filename}_confirm_no", use_container_width=True):
                st.rerun()

    @st.dialog("确认")
    def delete_note_btn_clicked(self, filename):
        st.write(f"您确定要删除 {filename} 吗？")
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("是", key=f"{filename}_confirm_yes", use_container_width=True):
                resp, status = delete_note(filename)
                if status == "deleted":
                    st.rerun()
        with col2:
            if st.button("否", key=f"{filename}_confirm_no", use_container_width=True):
                st.rerun()

    @st.dialog("确认")
    def delete_link_btn_clicked(self, link_id, title):
        st.write(f"您确定要删除 {title} 吗？")
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("是", key=f"{link_id}_link_confirm_yes", use_container_width=True):
                resp, status = delete_link(link_id)
                if status == "deleted":
                    st.rerun()
        with col2:
            if st.button("否", key=f"{link_id}_link_confirm_no", use_container_width=True):
                st.rerun()

    def edit_notes(self, file_url):
        filename = file_url.rsplit("/")[-1]
        content = fetch_file(file_url)
        with self.main_content:
            if settings.DEFAULT_EDITOR == "easymde":
                updated_content = easy_mde(
                    key=filename,
                    value=content,
                    height=600
                )
            else:
                updated_content = self.main_content.text_area(
                    f"以 Markdown 格式编辑 {filename}:",
                    value=content,
                    height=600
                )

            cols = self.main_content.columns([1, 1, 2, 2])
            if cols[0].button(
                    "← 返回列表",
                    key="back_to_list_button"
            ):
                st.session_state.view_mode = "notes-list"
                st.rerun()
            if cols[1].button(
                    "保存",
                    key="note_save_button"
            ):
                if updated_content:
                    st.session_state.right_sidebar_rendered = False
                    updated = update_note_to_api_server(
                        updated_content, file_url)
                    if updated:
                        st.session_state.updated_note_content = updated_content
                        st.success("文件更新成功")
                    else:
                        st.session_state.updated_note_content = None
                        st.error("更新文件时发生错误")

                    time.sleep(1)
                    st.rerun()

    def run(self):
        models = self.get_ollama_models()
        with st.sidebar:
            container = st.container()
            with container:
                col1, col2 = st.columns([1, 1])
                with col1:
                    st.title("个人知识库")
                with col2:
                    st.image(SVG_ICON, width=60)
            if models:
                if st.session_state.ollama_model_selected is None:
                    st.session_state.ollama_model_selected = models[0]
                selected_model = st.selectbox(
                    "选择对话模型",
                    options=models,
                    index=0,
                    key='select_ollama_model',
                    placeholder="选择一个模型...",
                    on_change=self.ollama_model_selected
                )
            else:
                st.info("暂无可用对话模型。请确保您的 Chat Provider（Ollama 或云端 API）配置正确。")
            discussion_mode = st.radio(
                "选择对话模式:",
                ["综合解答 (推荐)", "自由对话 (不参考文档)",
                    "仅检索并展示相关文档"]
            )

            input_context_window_size = st.number_input(
                label='输入检索引用窗口大小',
                min_value=1,
                max_value=100,
                value=3,
                step=1,
                format='%d'
            )

            input_method = st.radio(
                "选择知识库录入方式:",
                ["上传文件", "添加文本笔记", "添加网页链接",
                    "上传含链接的文件", "实验性递归抓取"]
            )

            if input_method == "上传文件":
                uploaded_file = st.file_uploader(
                    "上传一个文件", type=settings.UPLOAD_FILE_TYPES)
                if uploaded_file:
                    if st.button("处理文件"):
                        with st.spinner("处理文件中..."):
                            file_status, processed = self.process_uploaded_file(
                                uploaded_file)
                            if processed:
                                st.success("文件处理成功")
                            elif file_status == "error":
                                st.error("处理文件出错")
                            else:
                                st.success(
                                    f"文件处理耗时较长 - 请稍候... 状态={file_status}")
            elif input_method == "上传含链接的文件":
                uploaded_file = st.file_uploader(
                    "上传任意包含链接的文件", type=settings.UPLOAD_FILE_TYPES)
                if uploaded_file:
                    if st.button("处理文件"):
                        with st.spinner("处理文件中..."):
                            success = self.process_uploaded_file_with_links(
                                uploaded_file)
                            if success:
                                st.success("文件已提交处理")
                            else:
                                st.error("处理文件出错")
            elif input_method == "实验性递归抓取":
                st.subheader("输入链接")
                input_url = st.text_input("输入网址 (URL)", key="url_input_1")

                input_headers = st.text_area(
                    "请求头 (可选):",
                    height=150,
                    value=json.dumps(settings.DEFAULT_HEADERS, indent=2),
                    placeholder="以 JSON 格式粘贴请求头",
                    key="headers_input_1"
                )

                if input_url and input_headers and st.button("处理 URL", key="btn_url_1"):
                    try:
                        headers = json.loads(input_headers)
                    except:
                        st.error("无效的 JSON 格式")
                        headers = settings.DEFAULT_HEADERS

                    with st.spinner("处理中..."):
                        success = submit_recursive_crawl_link(
                            input_url, headers)
                        if success:
                            st.success("✅ 已提交处理！")
                        else:
                            st.error("处理出错")
            elif input_method == "添加网页链接":
                st.subheader("输入链接")
                input_url = st.text_input("输入网址 (URL)", key="url_input_2")

                input_headers = st.text_area(
                    "请求头 (可选):",
                    height=150,
                    value=json.dumps(settings.DEFAULT_HEADERS, indent=2),
                    placeholder="以 JSON 格式粘贴请求头",
                    key="headers_input_2"
                )

                if input_url and input_headers and st.button("处理 URL", key="btn_url_2"):
                    try:
                        headers = json.loads(input_headers)
                    except:
                        st.error("无效的 JSON 格式")
                        headers = settings.DEFAULT_HEADERS

                    with st.spinner("处理中..."):
                        success = submit_link(input_url, headers)
                        if success:
                            st.success("✅ 已提交处理！")
                        else:
                            st.error("处理出错")
            else:
                st.subheader("文本输入")
                input_text = st.text_area(
                    "在此输入您的文本:",
                    height=300,
                    placeholder="在此粘贴或输入您的文本..."
                )
                st.subheader("添加标题")
                input_title = st.text_area(
                    "输入笔记标题:",
                    height=70,
                    placeholder="输入标题.."
                )
                if input_text and input_title and st.button("处理文本"):
                    with st.spinner("处理文本中..."):
                        success = upload_note_to_api_server(
                            input_text,  input_title)
                        if success:
                            st.success(
                                "文本已处理并存储到向量数据库中！")
                        else:
                            st.error("处理文本出错")

        # Main chat interface
        self.display_chat_history()

        if discussion_mode == "综合解答 (推荐)":
            st.session_state.discussion_mode = "context-aware"
        elif discussion_mode == "自由对话 (不参考文档)":
            st.session_state.discussion_mode = "non-context-aware"
        else:
            st.session_state.discussion_mode = "only-links"

        if prompt := st.chat_input("提出关于已录入知识的问题"):
            st.session_state.messages.append(
                {"role": "user", "content": prompt})
            with self.main_content.chat_message("user"):
                st.markdown(prompt)

            if prompt.startswith("/notes-list"):
                st.session_state.view_mode = "notes-list"
            elif prompt.startswith("/links-list"):
                st.session_state.view_mode = "links-list"
            elif prompt.startswith("/files-list"):
                st.session_state.view_mode = "files-list"
            elif prompt.startswith("/notes-sync"):
                result = sync_notes()
                with self.main_content.chat_message("assistant"):
                    message_placeholder = st.empty()
                    self.qna_tab.container().empty()
                    full_response = f"总计更新了 {result['count']} 篇笔记"
                    message_placeholder.markdown(full_response)
            else:
                st.session_state.view_mode = "ollama-chat"
                prompt = self.set_source_type(prompt)

                st.session_state.context_window_size = input_context_window_size
                # only-links still uses search API for sidebar refs only
                if st.session_state.discussion_mode == "only-links":
                    docs = fetch_documents(prompt)
                    st.session_state.prompt_with_docs['docs'] = docs
                    st.session_state.prompt_with_docs['prompt'] = prompt
                    self.display_references()
                    st.session_state.is_generating = True
                    asyncio.run(self.process_response(docs, prompt))
                    st.session_state.is_generating = False
                else:
                    # context-aware / non-context: backend /chat does retrieve+generate
                    st.session_state.prompt_with_docs['docs'] = []
                    st.session_state.prompt_with_docs['prompt'] = prompt
                    st.session_state.is_generating = True
                    asyncio.run(self.process_response([], prompt))
                    st.session_state.is_generating = False
                    # refresh refs after citations arrive
                    if st.session_state.prompt_with_docs.get('docs'):
                        self.display_references()

        if st.session_state.prompt_with_docs and not st.session_state.right_sidebar_rendered:
            self.display_references(1)

        if st.session_state.updated_note_content is not None:
            st.markdown(st.session_state.updated_note_content)
            st.session_state.updated_note_content = None

        if (st.session_state.view_mode in ["notes-list", "links-list", "files-list"]
                    or st.session_state.list_page_number_modified
                ):
            st.session_state.list_page_number_modified = False
            if st.session_state.view_mode == "notes-list":
                self.display_notes()
            elif st.session_state.view_mode == "files-list":
                self.display_files()
            else:
                self.display_links()

        if st.session_state.view_mode == "edit-note":
            self.edit_notes(st.session_state.edit_note_url)

        if st.session_state.is_generating:
            if st.button("停止生成"):
                st.session_state.is_generating = False
                st.rerun()

        with st.sidebar:
            st.sidebar.divider()
            bottom_container = st.container()
            with bottom_container:
                col3, col4 = st.columns([1, 1])
                if col3.button("清除聊天记录", use_container_width=True):
                    st.session_state.messages = []
                    self.main_content.empty()
                    self.right_sidebar.empty()
                    st.session_state.source_type = None
                    st.empty()
                    st.session_state.prompt_with_docs.clear()
                    st.session_state.updated_note_content = None
                    st.rerun()
                if col4.button("使用提示", use_container_width=True):
                    st.markdown(TIPS)

        if st.sidebar.button(f"退出登录 ({st.session_state.get('username')}) ⬅️", use_container_width=True):
            navigate_to("logout")

        if st.session_state.authenticated:
            save_token_to_storage(st.session_state.get('token'),
                                  st.session_state.get('username'))
