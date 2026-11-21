# AI Coach OS 联网工作台与 API

## 本地启动

在项目根目录运行。此入口独立读取进程环境，使用 Supabase 测试项目和单进程内存会话。Streamlit 入口继续按其自身配置选择后端。

```powershell
& '.\.venv\Scripts\python.exe' -m pip install -e '.[web]'

$env:SUPABASE_TEST_PROJECT_REF = (Read-Host '已核对的测试项目 Ref').Trim()
$env:SUPABASE_URL = "https://$($env:SUPABASE_TEST_PROJECT_REF).supabase.co"
$env:SUPABASE_ALLOWED_COACH_IDS = (Read-Host '教练 Auth UUID，英文逗号分隔').Trim()
$key = Read-Host '测试项目 Publishable Key' -AsSecureString
$env:SUPABASE_PUBLISHABLE_KEY = [System.Net.NetworkCredential]::new('', $key).Password
$key.Dispose()

$env:AI_COACH_WEB_ORIGIN = 'http://127.0.0.1:8000'
& '.\.venv\Scripts\python.exe' -m uvicorn ai_coach_os.web.app:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

OpenAPI 文档位于 [本机 /docs](http://127.0.0.1:8000/docs)，接口前缀为 `/api/v1`。测试项目配置缺失或无效会导致启动失败。只在独立的测试终端配置凭据，结束后关闭终端。Web 进程不需要设置 `APP_DATA_BACKEND`。

## 工作台入口

打开 [联网工作台](http://127.0.0.1:8000/app/) 并使用已核对的测试教练账号。FastAPI 提供页面、`/app/assets/` 和同源 API。直接打开原型 HTML 文件仍进入本地演示。两种模式共享布局与样式，各自加载身份和业务状态。

| 页面或操作 | 联网请求 |
|---|---|
| 登录 | `POST /api/v1/auth/login` 成功后调用 `GET /api/v1/auth/me` |
| 整页刷新 | `GET /api/v1/auth/me` 恢复服务器会话，成功后重新加载目录 |
| 会员目录和返回目录 | `GET /api/v1/members` |
| 会员详情 | `GET /api/v1/members/{member_id}` |
| 训练历史 | 选择会员后调用 `GET /api/v1/members/{member_id}/training-sessions` |
| 退出 | `POST /api/v1/auth/logout`，从页面清除会员和训练数据。网络错误时可重试退出 |
| 新增训练记录 | 在会员的训练历史展开表单，调用 `POST /api/v1/members/{member_id}/training-sessions`，成功后重新读取训练历史 |

目录使用摘要中的姓名、目标、最近训练日期和课时。卡片头像使用姓名首字，数据库头像标识、电话和备注在详情读取。训练历史可展开查看反馈、备注和动作。首页统计、日程、AI 及其他业务写入仍在演示入口。联网页面内存保存目录和当前视图，浏览器整页刷新后从服务器重新读数据。

训练保存接收训练日期、1 至 40 个动作及可选的会员反馈和教练备注。与登录相同，POST 要求同源及自定义请求头。服务通过当前教练的 JWT 调用现有事务，返回 HTTP 201 及 `session_id`、`should_deduct_lesson`。同一会员同一训练日期首条记录触发扣课，余额最低为零。补录历史日期时，现有 RPC 会将最近训练日期设置为该次录入日期。每次成功 POST 创建一条独立记录；网络中断后先核对历史，避免重复录入。

## 接口

业务响应使用 `{"success":true,"data":...,"error":null}`。失败使用 `{"success":false,"data":null,"error":{"code":"...","message":"..."}}`。响应含 `Cache-Control: no-store`。日期、空值和字段名称沿用仓储契约。

| 方法与路径（相对 `/api/v1`） | 输入 | 成功响应的 `data` |
|---|---|---|
| `POST /auth/login` | JSON `{"email":"coach@example.invalid","password":"<本地输入>"}` | `{"id":"<已验证的 Auth UUID>"}`，响应设置会话 Cookie |
| `POST /auth/logout` | 无请求体 | `null`，服务端撤销本地会话并删除 Cookie |
| `GET /auth/me` | 会话 Cookie | `{"id":"<已验证的 Auth UUID>"}` |
| `GET /members` | 会话 Cookie | `MemberSummary[]`，包括 `id`、`name`、`remaining_lessons`、`goal`、`last_training_date`、`ai_reminder`、`today_plan_time` 和 `today_plan_available` |
| `GET /members/{member_id}` | 会话 Cookie、正整数会员 ID | `MemberDetail`，含 `id`、`name`、`avatar_emoji`、`created_at`、`remaining_lessons`、`goal`、`last_training_date`、`ai_reminder`、`phone`、`note` |
| `GET /exercises` | 会话 Cookie | `ExerciseOption[]`，每项仅有 `id`、`name` |
| `GET /members/{member_id}/training-sessions` | 会话 Cookie、正整数会员 ID | `TrainingHistoryItem[]`，含 `id`、`training_date`、`member_feedback`、`coach_note`、`raw_paste_text`、`created_at`、`exercises` |

训练历史先确认会员归属，动作项含 `exercise_name`、`weight`、`sets`、`reps`、`rpe`、`note`、`sort_order`。列表为空时返回 `[]`。会员列表的课表摘要当前不可用。原型中的训练主题、扣课标记、会员状态等展示字段需要在 HTML 接入时单独处理。所有 ID 沿用仓储整数。未来数据若超出浏览器安全整数范围，需要先更新传输契约。目录及训练历史沿用现有仓储的单次读取范围，未增加分页。

登录和退出必须带准确的 `Origin` 和 `X-AI-Coach-Request: 1`。后续 HTML 采用同源相对地址请求。服务不配置跨域凭据访问。所有 API 路由拒绝查询参数，接口不接受客户端指定身份。常见错误为未登录或失效 `401`、未准入或来源无效 `403`、会员不存在或不在教练范围内 `404`、无效输入 `422` 和统一的内部异常 `500`。

## 会话与安全边界

- Cookie 只含随机会话 ID。HTTPS 使用 `__Host-ai_coach_session`，带 `Secure`、`HttpOnly`、`SameSite=Lax`，范围为当前主机。回环 HTTP 开发使用不同的 Cookie 名，允许本地明文回环访问。
- `InMemorySessionStore` 通过 `SessionStore` 协议提供会话创建、加锁读取、更新和移除。空闲 30 分钟或绝对寿命 8 小时后会话失效。进程重启后需要重新登录。多进程部署需要共享存储，并保持同一会话的跨进程互斥。
- 每个请求从锁内读取最新快照，由共享 `SupabaseAuth` 恢复和刷新。新快照在释放锁前写回。恢复失败会移除本地会话，且查询不会被调用。退出先移除本地会话，再尽力通过共享核心撤销远端会话。
- 每个请求使用认证核心创建的当前教练客户端和 JWT 建立仓储。数据查询仍受现有 RLS 约束。响应只序列化仓储 DTO 和教练 UUID。服务端凭据和真实会员资料均不持久化到浏览器。

## 离线验证

```powershell
$env:RUN_SUPABASE_INTEGRATION_TESTS = '0'
$env:RUN_SUPABASE_MEMBER_RLS_SELECT_TESTS = '0'
& '.\.venv\Scripts\python.exe' -B -m unittest discover -s tests -p 'test_web_api.py' -v
& '.\.venv\Scripts\python.exe' -B -m unittest discover -s tests
```

API 测试使用 FastAPI TestClient 和模拟 Auth/Repository，并包含默认仓储构造及会话并发回归。真实账号和浏览器同源集成留待测试项目验收。

在项目根目录运行 `node prototype/verify-connected.mjs` 可用本机 Chrome 和回环 Mock FastAPI 验证浏览器流程。脚本需要 Node.js 22+ 和 Web 可选依赖，默认使用 Windows Chrome 和项目 `.venv`。可用 `AI_COACH_TEST_CHROME`、`AI_COACH_TEST_PYTHON` 指定其路径。测试覆盖浏览器会话、跨账号读取、网络失败和恢复、DOM 文本转义及本地存储隔离。
