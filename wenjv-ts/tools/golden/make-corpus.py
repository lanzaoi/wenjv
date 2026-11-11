import os
from pathlib import Path
from docx import Document
from pptx import Presentation
from pptx.util import Inches, Pt
from PIL import Image, ImageDraw
from pypdf import PdfWriter
from io import BytesIO

def make_corpus():
    out_dir = Path("tools/golden/corpus")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Markdown files
    md_samples = [
        ("# 问据知识库系统架构\n\n问据是一个私有部署的全栈个人知识库系统。\n\n## 核心模块\n\n- 向量检索：BGE-M3 嵌入模型\n- 语义重排：BGE-Reranker\n- 混合检索：RRF 与 BM25 全文检索\n\n| 特性 | 说明 |\n| --- | --- |\n| 存储 | SQLite WAL + LanceDB |\n| 语言 | TypeScript + Node.js |\n", "arch.md"),
        ("# TypeScript 全栈开发实践\n\nTypeScript 提供了强类型约束，消灭了运行时的类型不匹配错误。\n\n```typescript\ninterface User {\n  id: number;\n  name: string;\n}\n```\n\n## 最佳实践\n\n使用 Zod 运行时契约验证接口边界输入。\n", "ts-guide.md"),
        ("# 深度学习与知识图谱\n\n知识图谱通过实体与关系的网状结构连接信息。\n\n### 双向链接\n\n通过 [[双向链接]] 建立页面之间的联系，支持反向引用和自动建议。\n", "wiki-concept.md"),
        ("# 数据库选型与设计\n\nSQLite 是单机最可靠的关系型数据库，配合 WAL 模式能支持并发读取与高速写入。\n\n- PRAGMA journal_mode = WAL\n- PRAGMA synchronous = NORMAL\n", "db-design.md"),
        ("# 多模态检索原理\n\nSigLIP 2 模型将图像与文本映射到同一向量空间。\n\n支持以图搜图、以文搜图以及跨模态知识问答。\n", "multimodal.md"),
    ]
    for content, filename in md_samples:
        (out_dir / filename).write_text(content, encoding="utf-8")

    # 2. Text files
    (out_dir / "notes.txt").write_text("这是一篇普通的纯文本随手记笔记，用于测试纯文本解析器。\n问据系统支持 txt, md, docx, pptx, pdf 等全格式解析。", encoding="utf-8")

    # 3. HTML files
    html1 = """<!DOCTYPE html><html><head><title>Web 抓取与内容解析</title></head><body><article><h1>Web 抓取与内容解析</h1><p>Readability 算法可以过滤网页中的广告与导航栏，精确提取出正文内容与核心标题。</p></article></body></html>"""
    html2 = """<!DOCTYPE html><html><head><title>知识工程的前沿进展</title></head><body><article><h1>知识工程的前沿进展</h1><p>大语言模型结合 RAG 技术，能够在保持准确性的同时提供流畅的问答交互。</p></article></body></html>"""
    (out_dir / "article1.html").write_text(html1, encoding="utf-8")
    (out_dir / "article2.html").write_text(html2, encoding="utf-8")

    # 4. DOCX files
    for i in range(1, 4):
        doc = Document()
        doc.add_heading(f"DOCX 测试文档 第{i}篇", level=1)
        doc.add_paragraph(f"这是通过 python-docx 自动生成的测试文档 {i}，用于测试 mammoth 提取器。")
        doc.add_paragraph("系统应当能够无缝解析段落与文字，并支持分块检索。")
        doc.save(str(out_dir / f"doc_{i}.docx"))

    # 5. PPTX files
    for i in range(1, 3):
        prs = Presentation()
        # slide 1
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = f"演示文稿 {i}：问据系统"
        slide.placeholders[1].text = "第一页：系统概述与核心特性介绍"
        # slide 2
        slide2 = prs.slides.add_slide(prs.slide_layouts[1])
        slide2.shapes.title.text = "第二页：检索与向量化"
        slide2.placeholders[1].text = "LanceDB 向量索引与 SQLite 全文索引双轨协同"
        prs.save(str(out_dir / f"presentation_{i}.pptx"))

    # 6. Images
    for i in range(1, 4):
        img = Image.new("RGB", (200, 200), color=(50 * i, 70 * i, 100 + 20 * i))
        draw = ImageDraw.Draw(img)
        draw.text((20, 90), f"Test Image {i}", fill=(255, 255, 255))
        img.save(str(out_dir / f"image_{i}.png"))

    print(f"Generated synthetic corpus in {out_dir}: {len(list(out_dir.glob('*')))} files")

if __name__ == "__main__":
    make_corpus()
