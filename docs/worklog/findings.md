# 架构与环境关键发现 (Key Findings)

## 1. 上午多模态评测中断现场
- 上午评测针对 51 篇 ArXiv 论文（55 个跨模态问题）。
- 运行时因一次性向 Google API 批量请求数百张图片和文本切片的 embedding，触发了 Google AI Studio 的免费层配额上限（15 RPM / 1500 RPD 产生 429 报错）。
- 用户指示“测试停一下 谷歌额度超了”后，任务被安全 abort。
- 中断前已完成 5 个样本的微基准验证：Recall@5 达 100%，MRR@5 达 0.6500，产出了初始报告 `eval/mm_l2_l3_benchmark_report.md`。
- LanceDB 中残留数据为：`document_store` 25 条，`visual_store` 6 条。

## 2. 硬件与 Python 运行环境
- 活跃 Python 虚拟环境位于 `/home/lanzao/antigravity/dazzling-bell/.venv` (Python 3.14.8)。
- `onnxruntime` 1.31.0、`PIL` 13.0.0 已安装，支持 CPUExecutionProvider。
- 本地 CPU：Intel i7-13650HX（20 个逻辑核），跑 INT8 ONNX 仅需 ~10ms。
- 本机 GPU：NVIDIA RTX 5060 Laptop (8GB VRAM)，CUDA 13.2。
- 已安装 `tokenizers` 与 `transformers` 5.21.0。

## 3. 模型选型与 ONNX 规格
- 选用 `onnx-community/siglip2-base-patch16-224-ONNX`。
- 视觉塔：`onnx/vision_model_int8.onnx` 仅 ~94.5 MB，或者 `vision_model_fp16.onnx` ~186 MB。
- 文本塔：`onnx/text_model_int8.onnx` ~283 MB，或者 `text_model_fp16.onnx` ~564 MB。
- Tokenizer：Google Gemma 256k 词表 (`tokenizer.json` ~34 MB)。
- 嵌入维度：768 维。
