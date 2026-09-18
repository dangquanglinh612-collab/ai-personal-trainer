# TASK 10 阶段 A：真实审计与映射

审计目录：`C:\Users\Lenovo\Desktop\project attempt_backup_before_task4`。日期：2026-09-14。

## 代码与运行状态

- 入口 fitness.py → src/ai_coach_os/application.py，页面位于 ui/views/。
- SQLite 连接、DDL、seed：repositories/database.py；会员、身体数据、训练、照片：repositories/member_data.py；预约：repositories/appointments.py；AI调用与报告/计划数据库操作混合在 services/ai.py。
- coach_id 当前为 TEXT 用户名。auth.py 查询 coaches.username/password 明文；database.py seed 示例账号。不会迁移密码；新身份来自 Auth UUID。
- training_sessions 创建/动作/扣课在 save_training_session 的 BEGIN IMMEDIATE 同一事务；更新替换子项而不扣课。页面已接入 TASK 9 草稿确认。
- 预约创建/更新 SQLite BEGIN IMMEDIATE 锁内检查；非 cancelled 均占时段。PostgreSQL 使用 GiST 排斥约束，包括 UPDATE/状态恢复。
- 本地照片是 uploads/training_photos/ 下生成文件名，training_session_photos.file_path 存相对路径；本次照片记录和目录文件均为 0。
- services/ai.py 通过 st.secrets 后备 os.getenv 读取 AI key，urllib 调用 OpenAI-compatible 接口；不另建 AI client。现场未发现项目根 .env 或 .streamlit/secrets.toml。没有读取/输出真实密钥。
- requirements.txt 为 -e .，依赖由 pyproject.toml 管理；新增 supabase>=2,<3。本次隔离 .venv 用于依赖/离线验证，已忽略。
- Git 当前 main，没有首个 commit，也没有 remote；项目文件大量未跟踪。未执行 git add/commit/push。非源码技能包和修复输出需排除提交。
- 已核对 assets/login_bg.png 的代码路径与文件名大小写；Cloud Linux 路径使用 pathlib，不保留 Windows 路径作 Storage 来源。
- 原有测试基线 52 项通过。新测试报告见下文/阶段交付。

## 真实表数量与去向

| SQLite 表 | 行数 | PostgreSQL 去向 |
|---|---:|---|
| coaches | 2 | 手工 Auth 用户 + profiles；密码不迁移 |
| members | 5 | members |
| exercise_library | 20 | exercise_library（共享只读） |
| body_measurements | 0 | body_measurements |
| training_sessions | 6 | training_sessions |
| training_session_exercises | 10 | training_session_exercises |
| ai_analysis_reports | 1 | ai_analysis_reports |
| training_plans | 0 | training_plans |
| training_plan_exercises | 0 | training_plan_exercises |
| appointments | 0 | appointments |
| training_session_photos | 0 | training_session_photos，路径改为 bucket/object |
| lesson_plans | 3 | legacy / not migrated，当前仅 seed 写入，无页面读取 |
| training_logs | 0 | legacy / not migrated，无当前页面读取 |
| sqlite_sequence | 内部表 | 不迁移；RPC 校准 PostgreSQL identity |

这些旧表和本地文件均未删除。没有把旧 lesson_plans 的 3 条示例预约自动转换为 appointments。

## 字段映射（以真实数据库为准）

相同名称字段原样映射。整数 ID → bigint identity（BY DEFAULT，允许保留旧 ID）。coach_id TEXT → uuid 引用 auth.users。日期空字符串 → NULL；必填业务日期为空则阻止迁移。无时区 created_at/updated_at 按原机 Asia/Shanghai +08:00 解释后转 UTC；这是明确迁移假设，其他来源时区需先确认。

组数/次数/RPE、身体数据与重量仍为 text：当前允许空串或自由输入，不能强制转数值而丢失记录。members 保留真实 goal/note/remaining_lessons/ai_reminder，不凭提示词新增 join_date/total_lessons/training_goal 等字段。

**发现的历史字段差异：members.avatar_emoji 实际存在，但当前 init_db 不创建它；PostgreSQL 保留并迁移。** 对其他未映射字段脚本会阻止迁移，不静默丢弃。

### profiles

| PostgreSQL 字段 | 类型 | SQLite 来源 |
|---|---|---|
| id | uuid | coaches.username → coach mapping → auth.users.id |
| display_name | text | coaches.nickname（空时 username） |
| created_at | timestamptz | 数据库默认 now() |
| updated_at | timestamptz | 数据库默认 now() |

### exercise_library

| PostgreSQL 字段 | 类型 | SQLite 来源 |
|---|---|---|
| id | bigint | id |
| name | text | name |
| category | text | category |
| equipment | text | equipment |
| aliases | text | aliases |
| created_at | timestamptz | created_at |

### members

| PostgreSQL 字段 | 类型 | SQLite 来源 |
|---|---|---|
| id | bigint | id |
| coach_id | uuid | coach_id |
| name | text | name |
| created_at | timestamptz | created_at |
| remaining_lessons | integer | remaining_lessons |
| goal | text | goal |
| last_training_date | date | last_training_date |
| ai_reminder | text | ai_reminder |
| avatar_emoji | text | avatar_emoji |
| phone | text | phone |
| note | text | note |

### body_measurements

| PostgreSQL 字段 | 类型 | SQLite 来源 |
|---|---|---|
| id | bigint | id |
| coach_id | uuid | coach_id |
| member_id | bigint | member_id |
| record_date | date | record_date |
| height | text | height |
| weight | text | weight |
| body_fat | text | body_fat |
| waist | text | waist |
| hip | text | hip |
| note | text | note |
| created_at | timestamptz | created_at |

### training_sessions

| PostgreSQL 字段 | 类型 | SQLite 来源 |
|---|---|---|
| id | bigint | id |
| coach_id | uuid | coach_id |
| member_id | bigint | member_id |
| training_date | date | training_date |
| member_feedback | text | member_feedback |
| coach_note | text | coach_note |
| raw_paste_text | text | raw_paste_text |
| created_at | timestamptz | created_at |

### training_session_exercises

| PostgreSQL 字段 | 类型 | SQLite 来源 |
|---|---|---|
| id | bigint | id |
| session_id | bigint | session_id |
| exercise_id | bigint | exercise_id |
| exercise_name | text | exercise_name |
| weight | text | weight |
| sets | text | sets |
| reps | text | reps |
| rpe | text | rpe |
| note | text | note |
| sort_order | integer | sort_order |

### ai_analysis_reports

| PostgreSQL 字段 | 类型 | SQLite 来源 |
|---|---|---|
| id | bigint | id |
| coach_id | uuid | coach_id |
| member_id | bigint | member_id |
| report_date | date | report_date |
| report_markdown | text | report_markdown |
| input_summary | text | input_summary |
| created_at | timestamptz | created_at |

### training_plans

| PostgreSQL 字段 | 类型 | SQLite 来源 |
|---|---|---|
| id | bigint | id |
| coach_id | uuid | coach_id |
| member_id | bigint | member_id |
| plan_date | date | plan_date |
| status | text | status |
| source_analysis_report_id | bigint | source_analysis_report_id |
| plan_goal | text | plan_goal |
| coach_note | text | coach_note |
| raw_ai_plan | text | raw_ai_plan |
| created_at | timestamptz | created_at |
| updated_at | timestamptz | updated_at |

### training_plan_exercises

| PostgreSQL 字段 | 类型 | SQLite 来源 |
|---|---|---|
| id | bigint | id |
| plan_id | bigint | plan_id |
| exercise_id | bigint | exercise_id |
| exercise_name | text | exercise_name |
| target_weight | text | target_weight |
| sets | text | sets |
| reps | text | reps |
| target_rpe | text | target_rpe |
| note | text | note |
| sort_order | integer | sort_order |

### appointments

| PostgreSQL 字段 | 类型 | SQLite 来源 |
|---|---|---|
| id | bigint | id |
| coach_id | uuid | coach_id |
| member_id | bigint | member_id |
| appointment_date | date | appointment_date |
| start_time | time | start_time |
| end_time | time | end_time |
| status | text | status |
| note | text | note |
| training_plan_id | bigint | training_plan_id |
| training_session_id | bigint | training_session_id |
| created_at | timestamptz | created_at |
| updated_at | timestamptz | updated_at |

### training_session_photos

| PostgreSQL 字段 | 类型 | SQLite 来源 |
|---|---|---|
| id | bigint | id |
| coach_id | uuid | coach_id |
| member_id | bigint | member_id |
| session_id | bigint | session_id |
| bucket_name | text | 固定 training-photos |
| object_path | text | file_path → 校验文件 → UUID/会员/训练/确定性UUID.ext |
| original_filename | text | original_filename |
| caption | text | caption |
| created_at | timestamptz | created_at |

## 归属、Storage 与迁移风险

- 所有 coach 表均拆分 SELECT/INSERT/UPDATE/DELETE policy。会员相关表还校验 member 归属。
- 六张会员子表使用 (member_id,coach_id) 复合 FK；报告来源、关联计划、关联训练和照片还限定同一 member/coach，防止伪造外键。
- 两张动作子表由 parent EXISTS 校验所有权，不复制 coach_id。公共动作库不给普通用户写权限。
- 照片只允许项目 uploads/training_photos 内的真实文件，拒绝越界路径、缺失文件和 unsupported 扩展。无 session_id 的历史照片须人工处理，不能伪造训练归属。
- Storage 第一层路径必须是 auth.uid()，private bucket，signed URL 300 秒，只实时生成不持久化。
- dry-run 无 Supabase I/O。execute 必须显式确认项目 ref 和备份，Secret Key 只由脚本从本地环境读取；正式应用不读取 Secret Key。
- 远程幂等续跑采用同ID同内容跳过，不同内容阻止；照片名称由映射UUID/照片ID/文件哈希派生。不做破坏性覆盖。
- 真实数据库 dry-run 当前缺少两个 Auth UUID 映射，故按设计返回阻止迁移；不是已完成数据迁移。阶段 A 测试使用独立临时库和明确的测试 UUID，不把假映射写入正式项目。
- Docker 引擎未运行；SQL 静态/语法检查不等于 PostgreSQL 约束、并发或 Supabase RLS 实机通过。真实 integration 默认禁用。
- 阶段 A 不接线登录页和全业务 repository；APP_DATA_BACKEND 非 sqlite 时停止，避免误以为已经切换。下一阶段范围见 DEPLOYMENT.md。

## 阶段 A 最终验证结果

- 原有 52 项 + 新增 37 项离线测试 = **89 项通过**。
- 另有 1 项真实 Supabase 集成场景，默认跳过；本次明确设置 `RUN_SUPABASE_INTEGRATION_TESTS=0`。
- 在新建、被 Git 忽略的 `.venv` 内成功执行项目 editable install，验证 requirements 的本地打包布局。实际 SDK：supabase 2.31.0；Streamlit 1.63.0；pglast 8.4。`pip check` 无依赖冲突。
- schema / indexes / RLS / Storage / RPC 五份 SQL 通过 PostgreSQL parser；两段 PL/pgSQL 函数通过语法解析。Python compileall 通过。真实 SDK 客户端的离线构造检查通过，禁止网络的测试未触发请求。
- 原数据库 SHA256 保持 `3F3ED915AFB9528A014DA11B1BDA42A41240D2217A2713157D42CE516EA72031`。
- 没有连接/修改真实 Supabase，没有创建远程 Auth 用户、表、bucket，没有上传照片、迁移数据、提交 Git 或部署 Cloud。
- 不把 SQL parser 和 mock 测试称为数据库执行验收。本机 Docker 引擎未运行，PostgreSQL/RLS/Storage/并发实机与 Cloud/Linux/手机验收均留待后续阶段。

复现：`.venv\Scripts\python.exe -m unittest discover -s tests -q`，运行前保持真实集成开关关闭。新环境可 `python -m pip install -e ".[dev]"` 后测试。

## 本次文件清单

修改：`.gitignore`、`pyproject.toml`、`README.md`、`src/ai_coach_os/application.py`、旧教程 `docs/SUPABASE_DEPLOYMENT_GUIDE.md`（仅加历史方案提示）。

新增：

- `supabase/schema.sql`、`indexes.sql`、`rls.sql`、`storage.sql`、`rpc.sql`、`apply.psql.sql`。
- `src/ai_coach_os/services/supabase_client.py`。
- `scripts/migrate_sqlite_to_supabase.py`。
- `.streamlit/secrets.example.toml`、`migration_coach_map.example.json`。
- `tests/test_supabase_stage_a.py`、`tests/test_supabase_integration.py`。
- `docs/TASK10_AUDIT.md`、`docs/DEPLOYMENT.md`、`docs/BACKUP_AND_RESTORE.md`。

原 SQLite repositories、Auth 登录页面、训练保存/扣课、预约与 AI 业务代码未切换或重写。新的远程 adapter 是阶段 A 独立基础设施，不是已经完成的全业务后端替换。
