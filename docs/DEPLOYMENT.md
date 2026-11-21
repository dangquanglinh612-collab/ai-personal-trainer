# TASK 10 部署方案（阶段 A，本地准备，尚未上线）

当前根目录：`C:\Users\Lenovo\Desktop\project attempt_backup_before_task4`。

浏览器 → Streamlit Community Cloud（UI / Python / AI）
→ Supabase Auth（邮箱密码、UUID、JWT）
→ PostgreSQL（RLS）+ private Storage（训练照片）。

## 阶段边界

- A：SQL、独立客户端、迁移脚本、文档、离线测试。当前只完成此范围，不修改真实 Supabase。
- B：你确认后，连接专用测试项目并进行真实 RLS/Auth/Storage/RPC 验收。
- C：确认 SQLite 和 uploads 备份、创建 Auth 用户、核对映射后，显式执行迁移。
- D：完成剩余 repository 适配和 UI 路由接线，全部双后端回归通过后切换。
- E：迁移、GitHub 和安全检查完成后部署 Cloud；进行手机验收。

**目前不能用 Supabase 模式上线。** 默认仍是 SQLite。Supabase 接线仅供独立测试项目验收，当前范围是登录、退出、只读会员目录及详情。配置、认证或查询失败不会回退 SQLite；其余业务页面不会在该模式开放。

## 下一步 Dashboard 准备（不要发任何 Secret 到聊天）

1. 创建独立 Supabase 测试项目，记下项目 ref / URL。数据库密码只保存在密码管理器或本地环境。
2. 在项目 API Keys 页面取得 **Publishable Key**，只写本地 `.streamlit/secrets.toml` 或环境变量。
3. Auth → Users：创建两个不同邮箱的测试教练。密码/确认邮件在 Dashboard 和本人邮箱处理；不要复用 SQLite 示例密码。将 UUID 分别映射到 wenwen、numb。Auth 用户创建是用户在阶段 B/C 前的人工操作，脚本不会复制旧明文密码。
4. SQL Editor：等阶段 B 确认后，按下述事务顺序应用 SQL。若已有同名业务表，停止，不 DROP、不覆盖。
5. Storage：确认 `training-photos` 是 **private**。storage.sql 可创建该私有 bucket；若已存在 public 同名 bucket 会报错，需先人工审查。不要另建 public bucket。

可以在聊天提供：项目 URL/ref、两个测试用户的 UUID（或告诉我映射文件已填好）、“Publishable Key 已本地配置”、SQL/bucket 创建状态。**不要提供 Secret Key、用户密码、JWT、refresh token 或数据库密码。** 阶段 B 的普通连接测试不需要 Secret Key。

## SQL 应用顺序

先审阅 `supabase/schema.sql` → `indexes.sql` → `rls.sql` → `rpc.sql` → `storage.sql`。

在 SQL Editor 同一次执行中：`BEGIN;`，按顺序粘贴五个文件内容，最后 `COMMIT;`。不要先单独提交裸 schema 再隔一段时间启用 RLS。

`supabase/apply.psql.sql` 是 psql 包装脚本，含 `\ir`，**不能直接粘贴到 Dashboard**。它会事务化应用同一组文件并在首个错误停止。本次没有运行它。

Schema 是一次性空项目基线：同名表/策略重复执行将报错。这是保护而非“自动升级”；后续变更应另建增量 SQL。需要 `btree_gist` 扩展，用于预约教练 UUID + 半开时间区间的排斥约束。

所有业务表启用 RLS，普通客户端仅 authenticated；公共动作库仅 SELECT。父子表用 RLS + 复合 FK 双重归属保护。应用不在登录时写入 `profiles`，也不以 profile 是否存在判断教练授权。

## 本地配置和依赖

将 `.streamlit/secrets.example.toml` 的占位值复制到被 Git 忽略的 `.streamlit/secrets.toml`，当前保留 `APP_DATA_BACKEND = "sqlite"`。不要把真实 secrets 提交 Git。

使用 Python 3.12，`python -m pip install -e .`。`requirements.txt` 继续只有 `-e .`，依赖统一维护在 pyproject.toml，包括 supabase 2.x。不要在 requirements 另维护一份版本列表。

配置优先读取 Streamlit secrets，再读环境变量。后续验收时，`SUPABASE_TEST_PROJECT_REF` 必须取自独立测试项目 Dashboard，且与 `SUPABASE_URL` 精确匹配；`SUPABASE_PUBLISHABLE_KEY` 只接受 Publishable Key。`SUPABASE_ALLOWED_COACH_IDS` 是管理员配置的逗号分隔 Auth UUID，空名单、无效配置和非名单账号均拒绝准入。不提供公开注册；真实验收前由管理员在 Dashboard 确认关闭公开注册和匿名登录。不把此应用白名单当作 Data API 的数据库授权；开放更多业务前需另行审查数据库层授权。

每个浏览器的 session state 保存必要 token，不全局缓存客户端。每次 rerun 由会话层构造一个客户端，显式刷新临期或过期 token，再验证 UUID 并同步保存 token；仓储复用该客户端且不触发 Auth 刷新。退出尝试撤销当前会话并清除本地状态。页面整页刷新若重建 Streamlit session，预期重新登录。

`services/supabase_auth.py` 负责登录、恢复、刷新和撤销当前 Supabase 会话。`login()` 与 `restore()` 返回配对的客户端和认证快照。调用方负责保存新快照、在恢复失败时丢弃旧快照并停止使用其客户端，以及在退出时清理本地状态。Streamlit 的 `SupabaseSession` 负责这些状态操作，仍可从原有的 `services/supabase_client.py` 导入。

## 迁移：先 dry-run，再经确认 execute

1. 按 BACKUP_AND_RESTORE.md 备份 SQLite / uploads，并在迁移期间停止旧应用写入。
2. 复制 `migration_coach_map.example.json` 为 `migration_coach_map.json`，填写真实 Auth UUID，文件已被 Git 忽略。
3. 本地运行：

   ```powershell
   python scripts/migrate_sqlite_to_supabase.py --dry-run --coach-map migration_coach_map.json
   ```

   dry-run 只读 SQLite，不构造 Supabase 客户端，不需要远程 URL/key。检查表/字段、日期、归属、FK、预约冲突、照片路径和映射。未填写映射时会报错并退出，不伪造 UUID。无参数也是 dry-run，不是 execute。

4. 阶段 C 经确认后，只在本地环境设置 `SUPABASE_URL`、`SUPABASE_SECRET_KEY`（不放聊天、不放 Cloud），运行：

   ```powershell
   python scripts/migrate_sqlite_to_supabase.py --execute --coach-map migration_coach_map.json --confirm-project YOUR_PROJECT_REF --backups-confirmed
   ```

5. 脚本核对 Auth UUID、private bucket 和远程全量现有记录。未知远程 ID / 同 ID 不同内容会停止，**不 upsert 覆盖业务数据**。仅插入缺失行；保留原 ID。照片使用内容指纹生成确定性 UUID 路径，已有对象须下载校验哈希，不覆盖。上传成功才插 metadata；失败会列出 ID。
6. 调用管理员专用 sequence 校准 RPC，比较每表远程数量与源数量、照片校验数量。任何错误不宣布迁移成功。日志不打印业务内容或 SDK 内部密钥信息。

迁移不是跨 Auth、Storage、PostgreSQL 的分布式事务；部分完成时不自动回滚或删除远程/本地文件。保留报告，停止其他写入，核对失败 ID，再重复执行续跑。若 metadata 插入失败，照片可能成为私有孤立对象；重跑会验证复用，备份文档说明如何对账。不要在半迁移状态启动正式应用。

## 阶段 D 尚需完成的接线

`SupabaseRepository` 已由后端工厂绑定到当前认证用户，但不是全业务 SQLite repository 的即插即用替代品。适配器已有会员读取/创建、动作库、训练历史与原子保存、预约创建、照片上传/签名 URL。当前页面只接通会员读取。经真实隔离验收后，再逐步接入会员写入、身体数据、训练保存与照片、AI 报告/计划、预约修改与查询。计划头与子项保存需要事务；照片历史使用短期 signed URL。

训练 RPC 的创建逻辑：锁定会员 → 检查同日记录 → 插入训练与动作 → 按原规则扣课和更新日期，异常全部回滚。更新不扣课，也不额外修改原 SQLite 更新流程未修改的会员日期。没有新增持久幂等 token：超时后不可盲目重试创建；应先查询是否已保存。直接删除训练记录会影响同日存在性判断，保持现有 MVP 的规则，不擅自新增扣课流水功能。

## GitHub / Cloud 参数（阶段 E）

- Repository：尚无 remote，需用户创建/连接 GitHub 仓库，不虚构地址。
- Branch：当前 `main`，尚无首个 commit。
- Main file path：`fitness.py`。
- Python：3.12，与本地测试主版本一致。
- 工作根目录：仓库根，保留 src/、pyproject.toml、requirements.txt、assets/login_bg.png、.streamlit/config.toml。
- Cloud Secrets：`APP_DATA_BACKEND="supabase"`、`SUPABASE_URL`、`SUPABASE_PUBLISHABLE_KEY`、`DEEPSEEK_API_KEY`（或现有 OpenAI key）。**不配置 SUPABASE_SECRET_KEY**。

当前仓库有大量未跟踪的技能、压缩包、维修产物；不要 `git add .`。仅暂存审阅过的入口、src、tests、supabase、scripts、docs、构建文件、配置和所需 assets。确认 `git diff --cached` 没有数据库、照片、映射、密钥或本地备份，再提交。原 SQLite 的默认测试账号代码尚保留用于本地兼容，正式后端必须禁用它；当前版本还不是可直接公开部署的生产版。

## 测试与验收

### Stage 2：双教练只读验收

先在 Dashboard 人工核对 `ai-coach-os-phase2-test` 的准确项目 ref。在本地测试进程使用 `SUPABASE_TEST_PROJECT_REF`、`SUPABASE_TEST_URL` 和 `SUPABASE_TEST_PUBLISHABLE_KEY`；不得复用未核实的项目配置或 Secret Key。

管理员须预先准备两个独立的 Auth 账号和各自名下至少一条测试会员记录。两名教练的 UUID 都必须在应用实际配置的 `SUPABASE_ALLOWED_COACH_IDS` 中；将同一份白名单传入测试进程。另设置每组 `SUPABASE_TEST_UUID_A/B`、`SUPABASE_TEST_EMAIL_A/B`、`SUPABASE_TEST_PASSWORD_A/B`、`SUPABASE_TEST_MEMBER_ID_A/B`。缺少任何条件时不要启用测试，也不要由测试创建数据。

确认上述条件且只批准查询后，单独运行：

```powershell
$env:RUN_SUPABASE_MEMBER_RLS_SELECT_TESTS = '1'
python -B -m unittest discover -s tests -p test_supabase_member_rls.py
```

测试登录 Auth 后只对会员表发出 SELECT：分别验证自己的列表与详情、对方的 ID 和对方的 `coach_id` 条件，并通过相同用户 JWT 直接查询 Data API（不经过仓储的归属过滤）验证远端隔离。它不执行 SQL、不创建或清理数据。此阶段不要运行下方含写入的集成测试。

离线：`python -m unittest discover -s tests -v`。真实集成默认 skip；阶段 B 专用测试项目须经批准，设置 `RUN_SUPABASE_INTEGRATION_TESTS=1`、`SUPABASE_TEST_PROJECT_REF`、两组 `SUPABASE_TEST_UUID_A/B`、`SUPABASE_TEST_EMAIL_A/B` 与 `SUPABASE_TEST_PASSWORD_A/B`，并配置匹配的 URL 和 Publishable Key，才运行 `test_supabase_integration.py`。账号信息只放本地环境变量。测试会创建隔离测试会员及子记录、上传测试照片并清理，不在生产项目运行。

真实验收必须包括：两账号 CRUD RLS、子表与跨会员 FK、Storage 跨账号下载/覆盖/删除拒绝、JWT 刷新与退出、并发训练事务及失败回滚、预约并发、序列新增 ID、照片失败不影响训练、52项既有业务回归。Cloud 及手机还需测试登录、会员、AI智能粘贴、训练保存/历史、课表、照片；当前未取得线上 URL，未作手机验收。

## 官方依据

- [Supabase API keys](https://supabase.com/docs/guides/getting-started/api-keys)：普通请求使用 Publishable Key 与用户身份，Secret 管理权限独立。
- [Python set_session](https://supabase.com/docs/reference/python/auth-setsession)：恢复 session 并在过期时刷新。
- [RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)、[Storage access control](https://supabase.com/docs/guides/storage/security/access-control)：数据库行权限与文件目录策略。
- [Streamlit 依赖](https://docs.streamlit.io/deploy/concepts/dependencies)、[Cloud 部署](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)：部署依赖与仓库/入口配置。
