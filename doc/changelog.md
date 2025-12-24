# 变更记录

## 2025-12-24T16:04:22+08:00

### 修改目的

- 在汇总结果中显式列出未通过的 DBus 接口，便于快速定位问题项。

### 修改范围

- 更新 `tools/dbus_access_control_check.py`
- 更新 `doc/changelog.md`
- 新增 `.codex/plan/dbus-access-control-summary未通过列表.md`

### 修改内容

- `summary.json` 新增 `not_passed` 列表，记录 `fail/unknown/error` 的接口条目与状态。
- `results` 条目新增 `summary` 字段，便于汇总层直接判定通过状态。

### 对整体项目的影响

- 汇总层可直接识别未通过接口，不影响逐条输出结构与检查逻辑。

## 2025-12-24T15:45:49+08:00

### 修改目的

- 统一 `--only-method` JSON 输出字段命名，避免与下游数据规范不一致。

### 修改范围

- 更新 `tools/check_dbus_system_conf.py`
- 更新 `README.md`
- 更新 `doc/changelog.md`
- 新增 `.codex/plan/dbus-json字段改名.md`

### 修改内容

- `--only-method` 输出字段由 `dbus_path` 调整为 `path`，其余输出结构保持不变。
- 同步更新文档说明。

### 对整体项目的影响

- 下游消费字段名更统一；仅影响 `--only-method` 输出解析逻辑，其余模式不变。

## 2025-12-24T15:09:03+08:00

### 修改目的

- 提升命令注入检查提示词的安全约束，强调外部命令调用避免命令注入。
- 增加候选点预扫描提示，提升分析聚焦度与效率。

### 修改范围

- 更新 `prompts/command_injection_check.md`
- 更新 `tools/command_injection_check.py`
- 更新 `doc/changelog.md`
- 更新 `.codex/plan/命令注入检查-预扫描提示增强.md`

### 修改内容

- 提示词新增安全提示与 `rg` 预扫描候选点占位区。
- 工具新增 `rg` 预扫描，结果注入提示词并限制最大行数，覆盖无命中与错误场景。

### 对整体项目的影响

- 命令注入检查更聚焦候选点，提示约束更明确；输出结构与既有流程保持一致。

## 2025-12-24T14:45:16+08:00

### 修改目的

- 提升命令注入检查对 `sh -c` 数组/变量场景的检出率。

### 修改范围

- 更新 `prompts/command_injection_check.md`
- 更新 `doc/changelog.md`
- 更新 `.codex/plan/命令注入检查-sh-c检出增强.md`

### 修改内容

- 提示词新增检索指引，覆盖数组/切片变量传递场景。
- 显式执行示例补充变量数组形式的 `sh -c` 调用。

### 对整体项目的影响

- 降低 `cmdArgs = []string{"sh", "-c"}` 等场景漏检概率，输出结构不变。

## 2025-12-24T14:29:52+08:00

### 修改目的

- 命令注入检查忽略脚本/Makefile/注释等非代码场景，减少误报。

### 修改范围

- 更新 `prompts/command_injection_check.md`
- 更新 `tools/command_injection_check.py`
- 更新 `doc/changelog.md`
- 更新 `.codex/plan/命令注入检查忽略非代码场景.md`

### 修改内容

- 提示词新增非代码排除规则，明确忽略脚本、Makefile 与注释中的 shell 解释器提及。
- 工具支持提示词变量渲染，将非代码排除规则注入提示词。

### 对整体项目的影响

- AI 命令注入检查更聚焦实际代码调用点，降低脚本/注释带来的噪声。
- 现有输出结构保持不变。

## 2025-12-24T13:27:35+08:00

### 修改目的

- 为 polkit implicit 检查增加仅输出风险项的参数，便于批量结果聚焦。

### 修改范围

- 更新 `tools/check_polkit_action_implicit.py`
- 更新 `doc/architecture.md`
- 更新 `doc/changelog.md`
- 新增 `.codex/plan/polkit-implicit仅输出风险项.md`

### 修改内容

- 新增 `--only-flagged` 参数：JSON 结果仅保留风险项与错误项；文本输出抑制非风险输出与 summary。
- 更新架构文档中该工具能力描述。

### 对整体项目的影响

- 输出更聚焦高风险/待人工分析项，便于对接门禁或后续人工复核流程。
- 默认行为保持不变；新参数为可选增强。

## 2025-12-24T13:19:52+08:00

### 修改目的

- 为 polkit implicit 配置引入风险分级输出，区分高风险与待人工分析项。

### 修改范围

- 更新 `tools/check_polkit_action_implicit.py`
- 更新 `doc/architecture.md`
- 更新 `doc/changelog.md`
- 新增 `.codex/plan/polkit-implicit风险分级.md`

### 修改内容

- 新增隐式授权值的风险分级：`yes` 标记为高风险，`auth_self/auth_self_keep` 标记为待人工分析。
- 文本输出新增 `RiskLevel/RiskFields`；JSON 结果新增 `risk_level/risk_fields`。
- 更新架构文档中该工具的描述以体现分级规则。

### 对整体项目的影响

- 风险报告可直接区分高风险与待人工分析项，提升复核效率与整改优先级排序。
- 新增字段为增量输出，不影响现有脚本主流程；下游若需消费风险分级可按新字段解析。

## 2025-12-24T11:00:43+08:00

### 修改目的

- 补齐 AI 检查工具与提示词的架构说明，并在 README 中提供使用指引。

### 修改范围

- 更新 `doc/architecture.md`
- 更新 `README.md`
- 新增 `.codex/plan/AI检查文档更新.md`

### 修改内容

- 在架构文档中补充 AI 检查组件、提示词与 UML（Mermaid）结构图，并关联 AI 架构细化文档。
- 在 README 中新增 AI 检查工具说明、输入输出约定与环境依赖（`codex` CLI）。
- 记录本次文档更新计划。

### 对整体项目的影响

- AI 检查工具与提示词被纳入统一的架构与使用文档，便于交付/门禁对齐与持续维护。
- 仅文档变更，不影响现有脚本行为。

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

## 2025-12-22T16:35:44+08:00

### 修改目的

- 增强 `check_service_cap.py`：支持从文件批量读取 service；支持通过 `--expected-caps` 校验期望 Cap，不一致时返回退出码 `3`，便于门禁自动判定。

### 修改范围

- 更新 `tools/check_service_cap.py`
- 新增 `.codex/plan/systemd-service-cap工具增强.md`
- 更新 `doc/architecture.md`
- 更新 `doc/changelog.md`

### 修改内容

- 新增 `--services-file`：从文件读取待检查的 unit（每行一个）。
- 新增 `--expected-caps`：从文件读取期望 Cap（每行一个），与实际 `effective_capabilities` 对比；不一致时标记为 mismatch 并返回退出码 `3`。
- 增强 JSON 输出：输出 `results` 列表及 `summary` 汇总，便于 CI 消费。

### 对整体项目的影响

- 可一次性对一组 service 做一致性检查；与期望 Cap 文件配合可直接作为门禁脚本使用。
- JSON 输出结构发生变化（统一输出为包含 `results/summary` 的对象），如有既有解析脚本需同步调整。

## 2025-12-22T16:49:18+08:00

### 修改目的

- 修复批量模式下 summary 的 `not_found` 误判：兼容 service 列表文件/期望 cap 文件的 UTF-8 BOM 与零宽字符，避免 unit 名被污染导致 `LoadState=not-found`。

### 修改范围

- 更新 `tools/check_service_cap.py`
- 新增 `.codex/plan/service列表summary误判修复.md`
- 更新 `doc/changelog.md`

### 修改内容

- 读取文件统一使用 `utf-8-sig`，自动剥离 BOM。
- 额外清理零宽字符（如 `\ufeff`/`\u200b` 等），并对命令行传入的 service 名同样做规范化。

### 对整体项目的影响

- 解决常见“肉眼看起来正确但实际 unit 名包含不可见字符”的场景，summary 与实际查询一致性更高。

## 2025-12-22T17:05:28+08:00

### 修改目的

- 新增文件系统范围检查工具：读取 service 的 `ProtectSystem/ProtectHome/*Paths` 等配置，输出可读/可写范围摘要，并在显式使用 `/var/lib` `/var/run` `/run` 时提示优先使用 `StateDirectory=`/`RuntimeDirectory=`。

### 修改范围

- 新增 `tools/check_service_fs_scope.py`
- 新增 `.codex/plan/systemd-service-fs-scope检查工具.md`
- 更新 `doc/architecture.md`
- 更新 `doc/changelog.md`

### 修改内容

- 通过 `systemctl show <service> --property=...` 获取并解析 `ReadWritePaths/ReadOnlyPaths/InaccessiblePaths/ProtectSystem/ProtectHome/PrivateTmp/NoNewPrivileges` 等字段。
- 派生 `ReadableScope/WritableScope`，并输出文本或 JSON（含 `results/summary`）。
- 若 `*Paths` 中显式出现 `/var/lib` `/var/run` `/run` 路径前缀，输出提示字段 `prefer_state_runtime_directory_hint`。

### 对整体项目的影响

- “文件路径注入检查”可由工具提供结构化证据，减少人工翻看 unit 文件/配置的成本。
- 输出为派生结果，仍建议与 unit 文件评审、运行时验证结合使用。

## 2025-12-22T17:27:16+08:00

### 修改目的

- 新增 deb 包二进制权限检查工具：从包名列表读取已安装 deb 包，枚举其可执行文件并检查 capabilities 与 setuid/setgid（S 位），输出存在 Cap 或 S 位的二进制及其所属包。

### 修改范围

- 新增 `tools/check_deb_binaries_privilege.py`
- 新增 `.codex/plan/deb二进制cap与s位检查工具.md`
- 更新 `doc/architecture.md`
- 更新 `doc/changelog.md`

### 修改内容

- 使用 `dpkg-query -L <package>` 获取包内文件列表，过滤出可执行常规文件。
- 使用 `getcap` 获取可执行文件 capabilities；使用 `stat` 检测 `setuid/setgid` 位。
- 输出仅包含“有 capabilities 或 S 位”的二进制路径与所属包；支持 JSON 输出（含 `results/summary`）。

### 对整体项目的影响

- “deb 包二进制 Cap/S 位检查”可通过工具产出结构化证据，便于在 CD/交付检查或门禁脚本中复用。
- 工具依赖运行环境已安装对应包；若需要对未安装的 `.deb` 文件离线分析，需要单独扩展实现。

## 2025-12-22T17:37:19+08:00

### 修改目的

- 改进工具错误处理：区分“命令不存在”和“输入文件不存在”，避免误导性报错，并统一缺少命令时返回退出码 `127`。

### 修改范围

- 更新 `tools/check_service_cap.py`
- 更新 `tools/check_service_fs_scope.py`
- 更新 `tools/check_deb_binaries_privilege.py`
- 更新 `doc/changelog.md`

### 修改内容

- 缺少 `systemctl` / `dpkg-query` / `getcap` 时返回 `127`，并输出明确错误信息。
- 缺少输入文件（如 `--services-file` / `--packages-file` / `--expected-caps`）时返回 `1`，并输出 `file not found`。

### 对整体项目的影响

- 提升工具在 CI/CD 脚本中的可诊断性与一致性，减少因不可见环境差异导致的排障成本。

## 2025-12-22T17:52:52+08:00

### 修改目的

- 新增 polkit actionid 隐式授权检查工具：批量执行 `pkaction -a <actionid> -v`，当 `implicit any/inactive/active` 命中 `yes/auth_self/auth_self_keep` 时输出 actionid、所属包与配置。

### 修改范围

- 新增 `tools/check_polkit_action_implicit.py`
- 新增 `.codex/plan/polkit-actionid隐式授权检查工具.md`
- 更新 `doc/architecture.md`
- 更新 `doc/changelog.md`

### 修改内容

- 解析 `pkaction -v` 输出中的 `implicit any` / `implicit inactive` / `implicit active` 字段并判定风险值。
- 通过扫描 `*.policy` 文件定位 actionid 来源，使用 `dpkg-query -S` 反查所属包。
- 支持 `--actions-file`（每行一个 actionid）、`--json` 输出与 `results/summary` 汇总。

### 对整体项目的影响

- “Polkit 配置合规检查”可由工具输出结构化证据，便于门禁/交付环节自动化筛查需要明道云登记的 actionid。

## 2025-12-23T09:46:23+08:00

### 修改目的

- 抽取工具公共逻辑为内部模块，减少重复代码与同类 bug 多点修复成本。

### 修改范围

- 新增 `tools/_common.py`
- 更新 `tools/check_service_cap.py`
- 更新 `tools/check_service_fs_scope.py`
- 更新 `tools/check_deb_binaries_privilege.py`
- 更新 `tools/check_polkit_action_implicit.py`
- 新增 `.codex/plan/tools公共模块抽取.md`
- 更新 `doc/architecture.md`
- 更新 `doc/changelog.md`

### 修改内容

- 统一实现：按行读取列表文件（支持 UTF-8 BOM/零宽字符清理）、外部命令执行、`systemctl show` 获取与 `key=value` 解析、缺少命令/缺少输入文件的错误分类与退出码。
- 各工具改为复用 `tools/_common.py`，减少重复实现并保持行为一致。

### 对整体项目的影响

- 工具代码更易维护，后续新增检查项可复用公共能力，降低实现与排障成本。

## 2025-12-23T09:53:59+08:00

### 修改目的

- 降低 Python 工具运行产生的缓存文件对工作区与评审的干扰。

### 修改范围

- 更新 `.gitignore`
- 新增 `.codex/plan/python缓存目录忽略.md`
- 更新 `doc/changelog.md`

### 修改内容

- 将 `tools/__pycache__/` 作为构建产物加入忽略列表。

### 对整体项目的影响

- 减少 `git status` 噪音与误提交风险，保持工具开发迭代过程更可控。

## 2025-12-23T10:17:01+08:00

### 修改目的

- 新增 DBus system.d 配置检查能力：识别 default policy 下的 `allow own` 并输出证据与归属包。

### 修改范围

- 新增 `tools/check_dbus_system_conf.py`
- 更新 `tools/_common.py`
- 更新 `tools/check_polkit_action_implicit.py`
- 新增 `.codex/plan/dbus-systemd默认policy-own检查工具.md`
- 更新 `doc/architecture.md`
- 更新 `doc/changelog.md`

### 修改内容

- 扫描 `/etc/dbus-1/system.d/` 与 `/usr/share/dbus-1/system.d/` 下所有 `*.conf`，解析 XML 并定位 `<policy context="default">` 下的 `<allow own="...">`。
- 对命中项通过 `dpkg-query -S` 反查所属 deb 包并输出到报告；支持 `--json` 输出与汇总统计。
- 将 `dpkg-query -S` 的解析/归属包查询抽取到 `tools/_common.py`，供 `check_polkit_action_implicit.py` 与新工具复用。

### 对整体项目的影响

- 为“DBus 系统总线配置合规”提供自动化证据输出，便于在 CI/CD 或交付检查中快速发现默认策略过宽的 `own` 授权。

## 2025-12-23T10:23:44+08:00

### 修改目的

- 降低 DBus system.d 扫描工具在 `--json` 模式下的输出噪音，便于 CI/脚本消费。

### 修改范围

- 更新 `tools/check_dbus_system_conf.py`
- 新增 `.codex/plan/dbus-systemd检查工具-only-flagged.md`
- 更新 `doc/changelog.md`

### 修改内容

- 新增 `--only-flagged`：`--json` 时仅输出命中项（flagged）与错误项（status!=ok），`summary` 仍反映全量扫描统计。

### 对整体项目的影响

- 结构化输出更聚焦风险项，降低解析与存储成本，同时保留全量扫描的总体统计信息。

## 2025-12-23T11:05:45+08:00

### 修改目的

- 增强 DBus system.d 扫描工具：对允许 root `own` 的 bus name，输出其 **未被 default policy deny 覆盖**的 methods，用于快速定位潜在“默认可调用”的高权限接口面。

### 修改范围

- 更新 `tools/check_dbus_system_conf.py`
- 新增 `.codex/plan/dbus-systemd-root-service方法暴露检查工具.md`
- 更新 `doc/architecture.md`
- 更新 `doc/changelog.md`

### 修改内容

- 新增 `--services-file`：读取 D-Bus bus name 列表，基于 conf 中 `<policy user="root"><allow own="...">` 判断 root service。
- 扫描并索引 `<policy context="default">` 下的 `deny send_*` 规则，按 `send_destination/send_path/send_path_prefix/send_interface/send_member/send_type` 匹配方法。
- 使用 `busctl --system introspect --xml-interface` 递归枚举 object tree 的 methods；从全量 methods 中剔除 default deny 覆盖项，输出剩余 methods（`service -> object path -> interface -> method`）。
- 输出同时包含该 service 对应的 conf 文件及其所属 deb 包（`dpkg-query -S`）；支持 `--json` 与 `--only-flagged` 结果过滤。

### 对整体项目的影响

- “DBus 高权限 service 默认暴露面”可被自动化生成证据，便于在交付检查/门禁中对 root-owned 服务的默认可调用方法面做风险收敛与整改跟踪。

## 2025-12-23T11:09:05+08:00

### 修改目的

- 提升 root service methods 模式的可用性与可诊断性。

### 修改范围

- 更新 `tools/check_dbus_system_conf.py`
- 更新 `.codex/plan/dbus-systemd-root-service方法暴露检查工具.md`
- 更新 `doc/changelog.md`

### 修改内容

- service 模式文本输出改为按输入列表逐个输出（包含 `Status`/首条 `Error`），便于逐条核对与排障。
- 修正缺少 `busctl` 时的错误传播路径，确保按约定返回 `127` 并输出明确错误信息。

### 对整体项目的影响

- 批量检查时输出更稳定、可读性更高，且在环境缺失依赖时可快速定位根因。

## 2025-12-23T11:27:47+08:00

### 修改目的

- 使 root service methods 模式更贴近实际使用场景：自动拉起服务并过滤不具备业务风险意义的通用接口方法。

### 修改范围

- 更新 `tools/check_dbus_system_conf.py`
- 新增 `.codex/plan/dbus-systemd-root-service工具增强-自动拉起与接口过滤.md`
- 更新 `doc/changelog.md`

### 修改内容

- `busctl introspect` 默认启用 `--auto-start=yes`，提升对 activatable service 的覆盖率。
- 枚举方法时排除 `org.freedesktop.DBus.Introspectable` / `org.freedesktop.DBus.Properties` / `org.freedesktop.DBus.Peer` 的 methods。

### 对整体项目的影响

- 输出聚焦更可能引发业务/安全风险的接口面，减少噪音；同时提升在交付环境中的可用性（可自动拉起被检查服务）。

## 2025-12-23T11:33:16+08:00

### 修改目的

- 当 root service 存在未被 deny 管控的 methods 时，用明确状态标识风险，便于下游自动化处理。

### 修改范围

- 更新 `tools/check_dbus_system_conf.py`
- 新增 `.codex/plan/dbus-root-service未管控method状态标记.md`
- 更新 `doc/changelog.md`

### 修改内容

- 新增 `status=uncontrolled`：当 root service 枚举到的 methods 在剔除 default policy deny 后仍有残留时，`status` 不再为 `ok`。
- `summary` 增加 `uncontrolled` 统计项。

### 对整体项目的影响

- CI/脚本可基于 `status` 直接筛选风险 service（无需再从 `methods` 是否为空推断），提升一致性与可维护性。

## 2025-12-23T11:43:01+08:00

### 修改目的

- 补齐项目级 README，降低工具落地与接入成本。

### 修改范围

- 新增 `README.md`
- 新增 `.codex/plan/README编写.md`
- 更新 `doc/changelog.md`

### 修改内容

- 统一说明：环境依赖、通用输入文件格式、各工具的用途/参数/退出码、文本/JSON 输出字段与状态语义。
- 补充示例命令（路径均使用双引号包裹，便于脚本化与跨环境复制）。

### 对整体项目的影响

- 提升可用性与可维护性：新成员可基于 README 快速接入工具到 CI/CD，并减少对实现细节的反复询问。

## 2025-12-23T13:17:28+08:00

### 修改目的

- 完善 `--json` 输出规范并减少无意义的输出噪音，便于下游脚本/门禁稳定消费。

### 修改范围

- 更新 `README.md`
- 更新 `tools/check_service_fs_scope.py`
- 更新 `tools/check_deb_binaries_privilege.py`
- 新增 `.codex/plan/README-json-schema与summary清理.md`
- 更新 `doc/changelog.md`

### 修改内容

- README 补齐各工具 JSON 输出字段 schema（包含 `results[].*` 与 `summary.*`，并说明字段存在条件与状态语义）。
- 移除 `check_service_fs_scope.py` 与 `check_deb_binaries_privilege.py` 的 `summary.mismatch`（该工具不产生 `mismatch` 状态）。

### 对整体项目的影响

- JSON 消费端可直接基于 schema 做解析与校验，减少“看代码猜字段”的对接成本；同时 summary 更精简，降低噪音与误解风险。

## 2025-12-23T17:22:21+08:00

### 修改目的

- 为 `check_dbus_system_conf.py` 增加 `--only-method`，在需要“纯 methods 三元组”时提供更易消费的 JSON 输出形态。

### 修改范围

- 更新 `tools/check_dbus_system_conf.py`
- 更新 `README.md`
- 新增 `.codex/plan/dbus-systemd检查工具-only-method.md`
- 更新 `doc/changelog.md`

### 修改内容

- 新增 `--only-method`：仅在 `--services-file + --json` 模式下生效，stdout 输出为 `[{dbus_path, interface, method}, ...]`。
- 保持原有退出码语义；该参数仅影响 JSON 输出结构，不改变方法枚举/deny 排除逻辑。

### 对整体项目的影响

- 下游可直接消费方法三元组列表，无需解析嵌套 `service -> path -> interface -> method` 结构；但启用该参数时 JSON 顶层结构从 `{results, summary}` 变为数组，已有解析需按需适配。

## 2025-12-23
- 更新：命令注入提示词移除Node.js示例，补充Go语言外部命令调用与分析流程要求。
- 新增：命令注入检查提示词 `prompts/command_injection_check.md`。
- 新增：命令注入检查工具 `tools/command_injection_check.py`。
- 更新：架构设计文档补充检查类型路由与项目级执行器。
- 更新：落盘JSON关闭ASCII转义，提升中文可读性。
- 更新：提示词规定无明确deny的DBus policy不能作为方法级控制，且基于调用者PID信息的控制视为不安全。
- 更新：提示词明确PID构造Polkit subject不安全，且存在非Polkit访问控制时禁止输出pass/high。
- 新增：DBus方法访问控制检查提示词模板。
- 新增：批量执行与汇总工具 `tools/dbus_access_control_check.py`。
- 更新：架构设计文档，补充新组件与数据流。
- 更新：计划文件 `dbus_method_access_control_check.md`。
- 目的：支持批量方法检查、固定JSON输出与结果汇总。
- 影响范围：`prompts/`、`tools/`、`doc/`、`.codex/plan/`。
- 对整体影响：完善静态检查流程并降低幻觉风险。
- 新增：架构文档与计划文件骨架。
- 目的：建立项目文档与开发约定。
- 影响范围：`doc/`、`.codex/plan/`。
- 对整体影响：为后续功能实现提供结构化基础。
