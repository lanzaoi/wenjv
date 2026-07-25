# eval/ — 检索评测与参数消融实验

本目录包含自托管个人知识库系统的量化检索评估脚手架、消融实验矩阵与决策文档。

## 目录与资产说明

> [!IMPORTANT]
> `eval/` 目录下的 `ab_matrix_*.csv/md` 与 `sample_*.json` 为项目受控跟踪的基线评测资产，其他大数据与临时运行记录已被 `.gitignore` 隔离。

### 1. 核心文档与报表
- [gate_decision.md](./gate_decision.md)：v1.3 RAG 检索管线配置门禁决策文档（含人工审查签署生效区域）。
- [ab_matrix_1.3.md](./ab_matrix_1.3.md) / [ab_matrix_1.3.csv](./ab_matrix_1.3.csv)：4 组消融矩阵（default, hybrid_off, rerank_on, mmr_off）在 1000 题上的评估基线报表。
- [sample_1000.json](./sample_1000.json)：从 MS MARCO 语料库中采样的 1000 题标准化评测基线数据（含 queries、passages 与 qrels ground-truth）。

### 2. MS MARCO 自动化流水线
- `download_msmarco.py`：自动下载并解压 MS MARCO Passage Ranking 数据集至 `msmarco_data/` 目录（幂等校验，支持断点跳过）。
- `sample_msmarco.py`：从海量语料中抽取指定规模的正负样本段落并生成 `sample_1000.json`。
- `ingest_msmarco.py`：调用任务队列将测试段落摄入 LanceDB 向量存储库。
- `scoring.py`：信息检索（IR）指标评估核心，计算 **MRR@10**、**Recall@5** 与 **Recall@10**。
- `run_eval.py`：针对单次参数配置的检索评测运行器。
- `run_matrix.py`：自动化消融矩阵跑批工具，具备单个 Config 异常捕获隔离与增量写入防丢能力。

## 快速使用

```bash
# 1. 准备数据与抽样（如未生成 baseline）
python eval/download_msmarco.py
python eval/sample_msmarco.py

# 2. 写入向量存储
python eval/ingest_msmarco.py

# 3. 执行消融矩阵评估
python eval/run_matrix.py
```
