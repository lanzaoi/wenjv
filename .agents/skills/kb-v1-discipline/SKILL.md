---
name: kb-v1-discipline
description: "Use for any implementation work on this personal KB repo during 1.0 dual-cloud effort. Enforces SDD task scope, freeze list, dual-provider B0 limits, and report template."
---

# 个人知识库 1.0 纪律

真源计划：`.hermes/plans/2026-07-23_111953-v1-env-to-runnable.md`  
规范索引：`specs/README.md`  
卫生：`specs/git-and-ai-hygiene.md`

## 你是谁

实现助手，**不是**产品负责人。冲突顺序：

```text
可运行代码 > specs/ > plan > 聊天
```

## 今日范围（冻结）

**做：** Provider B0（SiliconFlow emb + DeepSeek chat 可配）、Ollama 可切回、主路径笔记+txt/md、挡路 bug、pytest 绿、README/相关 specs。

**不做：** hybrid、拒答产品化、Vue、Compose、删 Ollama、Provider B1/B2 平台化、PDF/链接作为门禁、大重构、录屏。

## 执行

1. 只做用户指定的 **当前 Task**；未列路径默认禁止改。
2. 先读相关 specs + plan 中该 Task 节。
3. 行为代码优先 TDD（见 `test-driven-development`）；配置字段可先测 settings。
4. 完成前必须跑验证命令（见 `verification-before-completion`）。
5. 用下方模板汇报；需要扩 scope → **STOP 提问**，不要擅自做。

## 汇报模板

```text
## 做了什么
- ...

## 改动路径
- ...

## 未做 / 故意不做
- ...

## 验证
- 命令：...
- 结果：...

## 文档
- [ ] 无需改 specs
- [ ] 已改：...

## 风险
- ...
```

## 表面功夫 = 失败

删断言、盲 skip、空 except 只为变绿、无关全库 format、虚假「全部 E2E 通过」、未跑命令声称完成。
