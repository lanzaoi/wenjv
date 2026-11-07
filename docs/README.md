# docs/ — 项目文档索引

本目录汇总 `wenjv`（问据）的项目级文档。根目录只保留 `README.md`（安装与使用说明），其余文档在此按用途分组。

## 规范与产品文档

规格类文档（架构、API、RAG、安全、代码约定）位于 [`../specs/`](../specs/)，索引见 [`../specs/README.md`](../specs/README.md)。

| 文档 | 说明 |
|------|------|
| [`wenjv_context_and_roadmap.md`](./wenjv_context_and_roadmap.md) | 项目全景：背景、多模态架构与长期演进路线 |
| [`UPGRADE_ROADMAP.md`](./UPGRADE_ROADMAP.md) | 已完成的分阶段改造清单（Phase 1–8）与核心接口说明 |
| [`deployment-diagram.md`](./deployment-diagram.md) | 部署架构图 |

## 审计与扫描记录（历史）

| 文档 | 说明 |
|------|------|
| [`ENGINEERING_HYGIENE_AUDIT.md`](./ENGINEERING_HYGIENE_AUDIT.md) | 工程卫生审计报告 |
| [`code-scan-todo.md`](./code-scan-todo.md) / [`code-scan-todo-v2.md`](./code-scan-todo-v2.md) | 历史代码扫描待办（早期版本，部分结论已被 v2 推翻，仅供参考） |

## 任务日志（worklog/）

SigLIP 2 ONNX 本地视觉嵌入集成任务的过程记录：

| 文档 | 说明 |
|------|------|
| [`worklog/findings.md`](./worklog/findings.md) | 架构与环境关键发现（硬件、模型选型、ONNX 规格、中断现场） |
| [`worklog/task_plan.md`](./worklog/task_plan.md) | 任务目标、验收标准与里程碑 |
| [`worklog/progress.md`](./worklog/progress.md) | 任务进度时间线 |

## 测试文档（testing/）

多模态基准评测测试基础设施说明：

| 文档 | 说明 |
|------|------|
| [`testing/TEST_INFRA.md`](./testing/TEST_INFRA.md) | `tests/test_benchmark_pipeline.py` 四层测试体系与里程碑接口契约 |
| [`testing/TEST_READY.md`](./testing/TEST_READY.md) | 测试套件就绪报告（28/28 通过记录） |

## 评测与测试代码

- 评测套件：[`../eval/`](../eval/)（索引见 [`../eval/README.md`](../eval/README.md)），报告位于 `eval/results/` 与 `eval/*_report*.md`。
- 自动化测试：[`../tests/`](../tests/)。
- 前端文档：[`../web/README.md`](../web/README.md)。
