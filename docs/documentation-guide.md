# AgentFlow 文档介绍

本目录用于说明 AgentFlow 的项目背景、设计方案、演示方式和参考素材。建议 GitHub 访问者先阅读根目录 README，再按目标选择下列文档。

## 推荐阅读顺序

1. [README](../README.md)：快速了解项目能力、本地运行方式、Docker Compose 启动方式和验证命令。
2. [项目介绍](project-introduction.md)：面向作品集和面试展示的项目定位、技术亮点、演示路径和简历表述。
3. [演示脚本](demo-script.md)：面试或项目展示时的讲解顺序，适合配合本地 Demo 使用。
4. [全栈设计规格](superpowers/specs/2026-07-15-agentflow-design.md)：完整产品设计、系统架构、数据模型、节点类型、执行语义和验收标准。
5. [实现计划](superpowers/specs/2026-07-15-agentflow-implementation-plan.md)：开发拆解、工程顺序和落地计划。

## 文档结构

```text
docs/
  project-introduction.md
  documentation-guide.md
  demo-script.md
  reference/
    agentflow-dashboard-reference.png
    agentflow-desktop-implementation.png
    agentflow-mobile-implementation.png
  superpowers/
    specs/
      2026-07-15-agentflow-design.md
      2026-07-15-agentflow-implementation-plan.md
```

## 各文档用途

- `project-introduction.md`：用于 GitHub 仓库介绍、作品集展示和面试前快速浏览。
- `documentation-guide.md`：用于说明文档入口和阅读路径，降低访客理解成本。
- `demo-script.md`：用于 3-5 分钟项目演示，帮助讲清“做了什么、怎么运行、有什么取舍”。
- `reference/`：保存项目视觉参考图和实现截图，便于理解界面目标。
- `superpowers/specs/`：保存设计规格与实现计划，体现从需求、架构到落地的完整思考过程。

## 面试使用建议

如果面试官时间有限，推荐先讲 `project-introduction.md` 中的项目定位、核心能力和演示亮点，再打开本地 Demo 展示一次工作流发布和运行监控。如果面试官追问技术细节，再进入设计规格文档说明 DAG 执行、版本管理、日志和 Mock Agent 的设计取舍。
