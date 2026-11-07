# eval/ — 检索与吞吐量化评测套件

本目录包含 `wenjv`（问据）知识库系统的检索精度评分核心、参数消融矩阵以及端到端综合评测脚本。

## 目录结构说明

- `scoring.py`：信息检索（IR）量化指标计算模块，提供 **MRR@10**、**Recall@K** 与 Bootstrap 置信区间计算。
- `run_eval.py`：单配置检索评测运行器。
- `run_matrix.py`：多配置消融矩阵跑批工具（支持异常隔离与增量写入）。
- `run_e2e_verification.py`：全链路三维综合验证脚本（覆盖结构感知切片、真实云端三模型检索精排与问答、微批并发吞吐压测）。
- `run_mm_l2_l3_eval.py`：基于 `eval/eval/open_ragbench_data`（ArXiv 多模态学术论文图表黄金问答集）的真多模态（L2 跨模态检索 + L3 VLM 像素直通推理）全量基准评测套件。
- `mm_l2_l3_benchmark_report.md`：Open RAGBench 多模态基准评测报告与技术结论。

## 快速运行

```bash
# 1. 运行端到端三维综合验证
PYTHONPATH=. python eval/run_e2e_verification.py

# 2. 运行 Open RAGBench 多模态 (L2 检索 + L3 推理) 评测
PYTHONPATH=. python eval/run_mm_l2_l3_eval.py
```
