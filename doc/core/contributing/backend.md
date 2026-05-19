# Rust API 贡献指南

## 分层方向

默认依赖方向：

```text
routes -> services -> job_snapshot_factory / job_launcher / runtime_gateway / db
job_runner -> db / config / runtime state
models 不反向依赖 routes 或 services
```

基本规则：

- `routes/*` 只做 HTTP adapter，请求解析、鉴权后入口和响应包装。
- `services/jobs/*` 放任务域业务逻辑，包括 query、presentation、creation、control。
- `job_runner/*` 放运行态执行、进程拉起、取消、OCR 子任务衔接和阶段推进。
- `models/*` 只放 DTO、输入输出模型、持久化模型，不放业务编排或文件系统读取。
- 不要为了省事把 `AppState` 传进只需要 `Db`、`AppConfig`、`Path` 或 semaphore 的 helper。

更细规则见 [Rust API 协同开发约定](../rust_api/09-协同开发约定.md)。

## API 改动

- 新增公开 API 字段时，使用稳定 view/model，不要把内部 `JobSnapshot` 字段直接暴露出去。
- 新增或改变接口、事件、产物 manifest、reader metadata、diagnostics、resume 行为时，更新 [API 文档](../api/index.md) 或对应 rust_api 文档。
- API 返回字段优先从 view/projection 层输出，不要在 route 里临时拼 JSON。
- 下载、预览、Range、ETag、reader regions 这类前端强依赖接口，应保持字段稳定和向后兼容。

## 常用检查

```bash
cargo fmt --manifest-path backend/rust_api/Cargo.toml --check
cargo test --manifest-path backend/rust_api/Cargo.toml
cd backend/rust_api && python3 scripts/check_architecture.py
```

## PR 说明

涉及 Rust API 的 PR 至少说明：

- 影响哪些 endpoint 或内部 service。
- 是否改变 job、artifact、reader、library、resume、diagnostics 等契约。
- 是否需要更新前端、桌面端或 API 文档。
- 已跑哪些 Rust 检查；没跑的说明原因。
