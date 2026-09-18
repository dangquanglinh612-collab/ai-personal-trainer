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

**目前不能仅设置 APP_DATA_BACKEND=supabase 就上线。** 阶段 A 已加 fail-closed 提示，防止配置为 Supabase 却继续写 SQLite。现有 SQLite 页面和保存函数保持原样。

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

所有业务表启用 RLS，普通客户端仅 authenticated；公共动作库仅 SELECT。父子表用 RLS + 复合 FK 双重归属保护。`profiles` 首次登录使用忽略冲突的 insert/upsert 初始化，不覆盖现有资料。

## 本地配置和依赖

将 `.streamlit/secrets.example.toml` 的占位值复制到被 Git 忽略的 `.streamlit/secrets.toml`，当前保留 `APP_DATA_BACKEND = "sqlite"`。不要把真实 secrets 提交 Git。

使用 Python 3.12，`python -m pip install -e .`。`requirements.txt` 继续只有 `-e .`，依赖统一维护在 pyproject.toml，包括 supabase 2.x。不要在 requirements 另维护一份版本列表。

客户端构造只接受新 Publishable Key；旧 key 项目需先在 Dashboard 创建新 key，不默认启用 legacy 兼容。每个浏览器 session_state 保存必要 token，不缓存登录 client、不使用全局 st.cache_resource。rerun 使用新客户端 set_session 恢复/刷新 token，并向 Auth 校验 user；失败清理全部状态。页面整页刷新若重建 Streamlit session，预期重新登录，不承诺跨新浏览器 session 持久登录。

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

独立 `SupabaseSession` / `SupabaseRepository` 已准备，但不是全业务 SQLite repository 的即插即用替代品。当前示范接口覆盖会员读取/创建、训练原子保存、预约创建、照片上传/签名 URL。后续需要将会员编辑/续课、身体数据、训练历史与子项、AI报告/计划存取、预约编辑/状态/查询适配为现有 tuple/dict 格式，计划头+子项保存亦须事务 RPC。登录页仅在 Supabase backend 使用邮箱密码；照片历史改用 signed URL。完成后才解除阶段 A 后端保护。

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

离线：`python -m unittest discover -s tests -v`。真实集成默认 skip；阶段 B 专用测试项目设置 `RUN_SUPABASE_INTEGRATION_TESTS=1`、`SUPABASE_TEST_PROJECT_REF`、两组 `SUPABASE_TEST_EMAIL_A/B` 与 `SUPABASE_TEST_PASSWORD_A/B` 后才运行 `test_supabase_integration.py`。账号信息只放本地环境变量。测试会创建隔离测试会员及子记录、上传测试照片并清理，不在生产项目运行。

真实验收必须包括：两账号 CRUD RLS、子表与跨会员 FK、Storage 跨账号下载/覆盖/删除拒绝、JWT 刷新与退出、并发训练事务及失败回滚、预约并发、序列新增 ID、照片失败不影响训练、52项既有业务回归。Cloud 及手机还需测试登录、会员、AI智能粘贴、训练保存/历史、课表、照片；当前未取得线上 URL，未作手机验收。

## 官方依据

- [Supabase API keys](https://supabase.com/docs/guides/getting-started/api-keys)：普通请求使用 Publishable Key 与用户身份，Secret 管理权限独立。
- [Python set_session](https://supabase.com/docs/reference/python/auth-setsession)：恢复 session 并在过期时刷新。
- [RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)、[Storage access control](https://supabase.com/docs/guides/storage/security/access-control)：数据库行权限与文件目录策略。
- [Streamlit 依赖](https://docs.streamlit.io/deploy/concepts/dependencies)、[Cloud 部署](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)：部署依赖与仓库/入口配置。
