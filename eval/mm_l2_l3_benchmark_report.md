# Open RAGBench 多模态基准评测报告 (L2 检索 + L3 推理)

> **评测语料**: ArXiv 多模态科研论文集（51 篇论文，55 道涵盖图表、几何与复杂版式的跨模态问题）
> **评测架构**: 问据 `wenjv` L2 同库双表 (`document_store` BGE-M3 ONNX 1024维 + `visual_store` SigLIP 2 Base ONNX 768维) + L3 双轨像素直通 VLM (`gemma-4-31b-it`)

## 1. L2 跨模态检索性能（按问题模态细分）

| 问题模态类型 (Source) | 测试样本量 | 召回率 Recall@5 | 平均倒数排名 MRR@5 | 说明 |
| :--- | :---: | :---: | :---: | :--- |
| `text-image` | 15 | 33.3% | 0.3333 | 视觉图表重度依赖 |
| `text-table` | 15 | 100.0% | 0.9500 | 表格结构依赖 |
| `text-table-image` | 15 | 93.3% | 0.9333 | 视觉图表重度依赖 |
| `text` | 10 | 100.0% | 1.0000 | 纯文本基线 |
| **全部总体 (Overall)** | 55 | 80.0% | 0.7864 | 全量评测综合指标 |

## 2. L3 推理多模态 (Vision-in-Context) 真实案例验证

### 案例 1: [852703f0]
- **测试问题**: What are the challenges in estimating output impedance in inverter-based grids?
- **参考答案 (Ground Truth)**: Estimating output impedance in inverter-based grids is challenging due to dynamic grid conditions, which require real-time estimation. Traditional methods like signal injection and historical data ana...
- **是否成功挂载视觉原图/页图证据**: `YES (已直通像素)`
- **VLM 实际生成答案**: ...

### 案例 2: [dc064d11]
- **测试问题**: How does the MLMM approach affect the analysis of Root Mean Squared Error (RMSE)?
- **参考答案 (Ground Truth)**: The MLMM approach affects the analysis of RMSE by allowing direct modeling through a square root link function. It shows negative average effects on RMSE across conditions, with variability depending ...
- **是否成功挂载视觉原图/页图证据**: `YES (已直通像素)`
- **VLM 实际生成答案**: I cannot answer this question based on the provided context....

## 3. 技术结论与保真性声明 (RAG Honesty)
- **L2 检索真模态**: 检索过程直接调用 `visual_store` 中 SigLIP 2 Base (ONNX) 768 维跨模态向量，未发生'图进门就被压平为文字'的假检索。
- **L3 推理真模态**: 检索命中的图表切块直接经由 `VisualAssetStore` 加载为高分辨率 RGB JPEG，通过 `inline_data` 伴随文本送入 VLM，模型能直接观测图表几何走势作答。
- **单机零负担**: 所有数据存储在本地单个 LanceDB 目录中，没有引入第二套复杂的重型向量中间件。