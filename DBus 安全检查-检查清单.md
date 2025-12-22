# DBus 安全检查清单

> 约定：
> - 每条检查使用 `- [ ]` 追踪执行状态。
> - 标签：`[CI]`/`[CD]` 表示检查阶段；`[AI]` 表示需要 AI 辅助静态分析。

## 1.DBus服务权限检查

- [ ] `[CD]` 检查 service Cap
  - 检查方法：
    - 检查 service Cap
    - 命令样例：`systemctl show ${service name} --property=CapabilityBoundingSet --property=AmbientCapabilities --property=User --property=Group --property=SupplementaryGroups`
  - 流程：
    1. 列出所有关注的 service 文件；
    2. 依次执行 systemctl show 获取 service 的信息；
    3. User 为空时认为是 root，CapabilityBoundingSet 为 service 的实际 Cap；
    4. User 不为空时，AmbientCapabilities 为 service 实际的 Cap；
    5. Group 和 SupplementaryGroups 两者相加为该 service 所在的 Group；
  - 输出：service 的 User、Cap 和 Group
  - 处理方法：人工分析后需要明道云归档，后续变更需要走流程

- [ ] `[CI]` 检查 service Cap 变更：判断修改 service 文件时，涉及到 User Group CapabilityBoundingSet AmbientCapabilities 的变动需要系统？架构加分
  - 输出：是否涉及 User、Cap 和 Group 的变动
  - 处理方法：在明道云登记变更流程
  - 备注：gerrit 门禁，暂停

- [ ] `[CD]` 检查 deb 包中的二进制的 cap，是否和明道云登记内容一致
  - 流程：`getcap` 获取二进制 Cap
  - 输出：二进制的 Cap
  - 处理方法：在明道云登记变更流程
  - 备注：目前测试已覆盖

- [ ] `[CD]` 检查 deb 包中的二进制是否 setuid/setgid
  - 流程：`stat`、`ls -l` 等命令查询二进制
  - 输出：二进制的 s 位权限
  - 处理方法：在明道云登记变更流程
  - 备注：目前测试已覆盖

## 2.文件路径注入检查

- [ ] `[CD]` 检查 service 的 ReadWritePaths ProtectSystem ProtectHome PrivateTmp InaccessiblePaths ReadOnlyPaths NoNewPrivileges
  - 检查方法：
    - 检查 service 的 ReadWritePaths ProtectSystem ProtectHome PrivateTmp InaccessiblePaths ReadOnlyPaths NoNewPrivileges
    - 如果有 `/var/lib`、`/var/run` 的使用，应该优先用 `StateDirectory=` / `RuntimeDirectory=`
  - 流程：
    1. 列出所有关注的 service 文件；
    2. 依次执行 systemctl show 获取 service 的信息；
  - 输出：service 的文件范围
  - 处理方法：人工分析后需要明道云归档，后续变更需要走流程

## 3.DBus接口通用访问权限控制检查

- [ ] `[CI][AI]` 检查是否有 polkit 鉴权
  - 检查方法：
    1. 接口逻辑是否会有鉴权，什么情况下不会进行鉴权；
    2. 鉴权的 action id 是否为当前项目配置的 action id；
  - 流程：AI 进行静态代码分析
  - 输出：无鉴权的 method
  - 处理方法：
    - 无鉴权、无访问控制的 method 需要进行评审，评审通过后需要明道云归档，后续变更需要走流程。
    - 违规配置立刻修改
  - 备注：gerrit 门禁

- [ ] `[CD]` 检查是否有 dbus.conf 访问权限控制（`/etc/dbus-1/system.d/`、`/usr/share/dbus-1/system.d/`）
  - 流程：
    1. 列出所有关注的 service 文件以及其 method；
    2. 加载所有 dbus.conf 配置；
    3. 输出违规的 allow_own 配置，以及记录没有限制调用的 method；
  - 输出：DBus 接口访问权限说明，是否存在违规的权限配置
  - 备注：gerrit 门禁

## 4.DBus接口自行实现的访问权限控制检查

- [ ] `[CI][AI]` 检查是否存在违规权限控制手段
  - 检查方法：
    1. 检查是否为 deepin-security-loader启动的应用。
    2. 检查是否通过 `GetConnUid`/`Gid` 类似的方式做访问控制。
    3. 不允许使用其他自行实现的手段进行访问权限控制。
  - 流程：
    1. 检查 `SetAllowCaller` 接口的权限配置；
    2. 检查所有 method 的访问控制手段；
  - 输出：是否存在违规权限控制手段

## 5.DBus接口命令注入检查

- [ ] `[CI][AI]` 检查执行的二进制为 bash sh shell dash 等脚本解释器这样的写法
  - 检查方法（重点关注）：
    1. `system`
    2. `subprocess.run shell=True`
    3. `g_spawn_command_line_async`
  - 流程：检查代码中是否有调用 bash dash sh 等
  - 输出：是否存在违规使用
  - 处理方法：立刻修改
  - 备注：gerrit 门禁

## 6.Polkit 配置合规检查

- [ ] `[CI]` gerrit 代码提交时，如果有修改 policy pkla rules policy.in pkla.in rules.in 文件，检查 allow_* 的配置
  - 流程：检查有关 polkit 配置
  - 输出：是否存在违规配置
  - 处理方法：立刻修改
  - 备注：gerrit 门禁

- [ ] `[CD]` `pkaction -a actionid -v` 检查 implicit any、implicit inactive、implicit active 字段是否为 yes 或 auth_self（yes/auth_self 需明道云登记）
  - 流程：检查有关 polkit 配置
  - 输出：是否存在违规配置
  - 处理方法：人工分析后需要明道云归档，后续变更需要走流程

- [ ] `[CI][AI]` 检查代码中是否有不安全的鉴权方式(非 sender 作为鉴权主体)
  - 流程：检查鉴权方式
  - 输出：是否存在违规的鉴权方案
  - 处理方法：立刻修改
  - 备注：gerrit 门禁
