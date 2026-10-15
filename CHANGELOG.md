# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/)（语义化版本）规范。

## [v1.2.0] - 2026-10-15

### ✨ Features
- 新增 RAG 评估体系（eval/test_set.json + eval/benchmark.py），支持标准化测试集自动打分
- 新增评估报告生成，输出总通过率、知识库内/外通过率、TTFT、引用覆盖率等指标

### 🔧 Changed
- 优化 Rerank 相关性阈值，提升知识库内问题的召回率

### 📝 Docs
- 更新 README，补充性能评估数据章节

## [v1.1.0] - 2026-10-11

### ✨ Features
- 实现知识库级别数据隔离（`kb_id` 全链路过滤：上传、列表、删除、向量检索、关键词检索）。
- 引入查询重写（Query Rewriting）实现 Agentic RAG 初步能力，解决多轮对话中代词指代导致的检索失败。
- Prompt 中增加安全指令，防止参考文档中的恶意指令注入。

### 🐛 Fixed
- 修复 Rerank 服务故障时的错误降级逻辑，改为明确报错而非盲目回退。
- 修复 CORS 配置，显式允许 `null` origin 与本地端口，解决 QtWebEngine 跨域拦截。
- 清理 `main.py` 中重复定义的接口函数，消除 Duplicate Operation ID 警告。

## [v1.0.0] - 2026-10-10

### ✨ Features
- 完成完整的 RAG 检索增强生成闭环（解析、切分、向量化、检索、生成）。
- 支持 PDF、Word、Excel 多格式文档的异步解析与入库。
- 引入 `BAAI/bge-m3` Embedding 和 `BAAI/bge-reranker-v2-m3` 重排序模型。
- 实现混合检索（向量 + 关键词 ILIKE）结合 RRF 融合算法。
- 支持 SSE 流式打字机输出，完美渲染 Markdown。
- 实现多会话管理（创建、切换、删除、自动命名与历史恢复）。
- 前端支持引用溯源，点击 `[1]` `[2]` 徽章可高亮右侧对应文档。
- 基于 PySide6 封装原生桌面客户端，支持原生文件上传。

### 🐛 Fixed
- 修复了 SSE 协议中换行符导致 JSON 解析失败的问题。
- 解决了 QtWebEngine 加载本地 HTML 时的跨域请求限制。
- 拦截 Rerank 低分结果，防止大模型幻觉。

### 📝 Docs
- 完善 README 保姆级快速启动指南。
- 增加 `docker-compose.yml` 和 `init.sql` 实现数据库一键部署。
- 补充 `start.bat` 一键启动脚本。
- 