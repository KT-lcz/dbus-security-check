# 变更记录

## 2025-12-22T16:04:07+08:00

### 修改目的

- 将 DBus 安全检查 CSV 转换为可执行的 Markdown 检查清单，便于评审/门禁/交付流程直接使用。

### 修改范围

- 新增 `DBus 安全检查-检查清单.md`
- 新增 `doc/architecture.md`
- 新增 `doc/changelog.md`
- 新增 `.codex/plan/DBus安全检查清单转换.md`

### 修改内容

- 按“检查项”聚合 CSV 记录（空“检查项”行归并到上一条检查项），生成分章节清单。
- 每条检查以 `- [ ]` 形式输出，并保留字段：检查阶段/检查方法/流程/输出/是否需要 AI/处理方法/备注。
- 对多行字段进行结构化展开（列表/分行），提升可读性与可执行性。

### 对整体项目的影响

- 文档从“表格”升级为“可执行清单”，更易在 CI 门禁、CD 交付检查与人工评审中落地。
- 不改变原始 CSV 数据；如 CSV 更新，需要同步更新 Markdown 清单以保持一致。

## 2025-12-22T16:20:26+08:00

### 修改目的

- 实现一个可复用的 Python CLI 工具，用于按传参检查单个 systemd service 的 Cap/User/Group 信息，支撑“DBus服务权限检查”落地自动化。

### 修改范围

- 新增 `tools/check_service_cap.py`
- 新增 `.codex/plan/systemd-service-cap检查工具.md`
- 更新 `doc/architecture.md`
- 更新 `doc/changelog.md`

### 修改内容

- 通过 `systemctl show <service> --property=...` 获取并解析 `User/Group/SupplementaryGroups/CapabilityBoundingSet/AmbientCapabilities` 等字段。
- 按检查表规则计算 `effective_capabilities`（root → `CapabilityBoundingSet`；非 root → `AmbientCapabilities`），并输出文本或 JSON。
- 提供明确退出码：成功 `0`、service 不存在 `2`、其他错误 `1`。

### 对整体项目的影响

- 将“service Cap”检查从纯人工步骤提炼为可执行工具，便于在 CD/交付环节复用与标准化。
- 工具依赖运行环境可访问 `systemctl`/system bus；在容器或无 systemd 环境下会返回错误并提示原因。
