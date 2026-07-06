# API 使用文档

本文档描述当前项目的 HTTP API。当前版本使用 **Gmail App Password + IMAP 只读同步**，默认后端地址为：

```text
http://127.0.0.1:8000
```

启动后也可以打开 FastAPI 自动文档：

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

## 认证方式

### Admin API

Admin API 路径前缀为 `/admin`，用于管理 Gmail 账号、代理、别名、API Key、同步和本地邮件。

如果 `backend/.env` 中配置了 `ADMIN_TOKEN`，所有 Admin API 请求都需要带：

```http
X-Admin-Token: your_admin_token
```

如果没有配置 `ADMIN_TOKEN`，Admin API 不校验该请求头，适合本机开发测试。

### Consumer API

Consumer API 路径前缀为 `/api/v1`，用于给其它应用读取已同步邮件。

所有 Consumer API 请求都需要带：

```http
X-API-Key: mg_xxx
```

API Key 由 Admin API 或后台页面创建。创建时返回的 `api_key` 只显示一次，后续接口只返回 API Key 元数据，不会再返回明文密钥。

## 通用约定

- 请求和响应默认都是 JSON。
- 时间字段使用 ISO 8601 格式，例如 `2026-07-06T12:30:00`。
- `id` 是本地 SQLite 数据库中的自增 ID。
- `gmail_message_id` 是 Gmail/IMAP 同步得到的邮件唯一标识。
- 删除邮件接口只删除本地已同步副本和本地缓存附件，不会删除 Gmail 原始邮件。
- 邮件同步是只读操作，不会标记已读、归档、删除或修改 Gmail 邮箱。
- FastAPI 错误响应通常为：

```json
{
  "detail": "error message"
}
```

## 快速接入流程

下面示例使用 PowerShell 的 `curl.exe`。如果启用了 `ADMIN_TOKEN`，请在 Admin API 示例中额外加入：

```powershell
-H "X-Admin-Token: your_admin_token"
```

### 1. 检查后端状态

```powershell
curl.exe "http://127.0.0.1:8000/admin/health"
```

示例响应：

```json
{
  "ok": true,
  "app": "Gmail Multi-Account Manager"
}
```

### 2. 可选：创建代理

如果账号同步需要走 SOCKS5 代理，例如 `socks5://127.0.0.1:7890`：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/admin/proxies" `
  -H "Content-Type: application/json" `
  -d "{\"name\":\"Local SOCKS5\",\"type\":\"socks5\",\"host\":\"127.0.0.1\",\"port\":7890,\"enabled\":true,\"is_global\":false,\"timeout_seconds\":20}"
```

建议创建后先测试 IMAP 连通性：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/admin/proxies/1/test-imap"
```

### 3. 添加 Gmail 账号

Gmail 账号需要先在 Google 账号中启用两步验证并创建 App Password。`app_password` 可以带空格，后端会自动规范化。

直连账号：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/admin/accounts" `
  -H "Content-Type: application/json" `
  -d "{\"email\":\"user@gmail.com\",\"app_password\":\"xxxx xxxx xxxx xxxx\",\"proxy_mode\":\"direct\",\"initial_sync_limit\":1}"
```

固定使用某个代理：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/admin/accounts" `
  -H "Content-Type: application/json" `
  -d "{\"email\":\"user@gmail.com\",\"app_password\":\"xxxx xxxx xxxx xxxx\",\"proxy_mode\":\"fixed\",\"proxy_id\":1,\"initial_sync_limit\":1}"
```

### 4. 测试账号登录

```powershell
curl.exe -X POST "http://127.0.0.1:8000/admin/accounts/1/test"
```

示例响应：

```json
{
  "ok": true,
  "email": "user@gmail.com",
  "error": null
}
```

### 5. 生成 Gmail plus aliases

```powershell
curl.exe -X POST "http://127.0.0.1:8000/admin/accounts/1/aliases/generate" `
  -H "Content-Type: application/json" `
  -d "{\"pattern\":\"shop-{n:00}\",\"count\":5,\"label\":\"shop\"}"
```

`user@gmail.com` 会生成类似：

```text
user+shop-01@gmail.com
user+shop-02@gmail.com
user+shop-03@gmail.com
user+shop-04@gmail.com
user+shop-05@gmail.com
```

### 6. 同步最新邮件

默认手动同步只拉取最新 `1` 封邮件：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/admin/accounts/1/sync" `
  -H "Content-Type: application/json" `
  -d "{\"limit\":1}"
```

手动拉取更多邮件：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/admin/accounts/1/sync" `
  -H "Content-Type: application/json" `
  -d "{\"limit\":20}"
```

### 7. 创建 Consumer API Key

不限制账号和别名：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/admin/api-keys" `
  -H "Content-Type: application/json" `
  -d "{\"name\":\"local integration\",\"rate_limit_per_minute\":120}"
```

限制只能读取账号 `1` 和指定别名：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/admin/api-keys" `
  -H "Content-Type: application/json" `
  -d "{\"name\":\"shop app\",\"account_ids\":[1],\"aliases\":[\"user+shop-01@gmail.com\"],\"rate_limit_per_minute\":60}"
```

示例响应中的 `api_key` 需要保存到调用方：

```json
{
  "id": 1,
  "name": "local integration",
  "active": true,
  "account_ids": [],
  "aliases": [],
  "ip_allowlist": [],
  "rate_limit_per_minute": 120,
  "last_used_at": null,
  "created_at": "2026-07-06T12:30:00",
  "updated_at": "2026-07-06T12:30:00",
  "api_key": "mg_xxx"
}
```

### 8. 外部应用读取邮件

```powershell
curl.exe -H "X-API-Key: mg_xxx" "http://127.0.0.1:8000/api/v1/messages?limit=20"
```

查看邮件详情：

```powershell
curl.exe -H "X-API-Key: mg_xxx" "http://127.0.0.1:8000/api/v1/messages/1"
```

## Admin API

### 健康检查

#### `GET /admin/health`

返回后端是否可用。

### 账号管理

#### `GET /admin/accounts`

返回所有 Gmail 账号。

响应字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 本地账号 ID |
| `email` | Gmail 地址 |
| `auth_type` | 当前为 `app_password` |
| `status` | `active`、`auth_failed`、`proxy_failed`、`rate_limited`、`disabled` |
| `proxy_mode` | `auto`、`direct`、`fixed` |
| `proxy_id` | 固定代理 ID |
| `sync_enabled` | 是否启用同步 |
| `initial_sync_days` | 同步搜索窗口天数 |
| `initial_sync_limit` | 默认同步数量，当前默认 `1` |
| `last_sync_at` | 最近同步时间 |
| `last_error` | 最近错误 |
| `app_password_configured` | 是否已配置 App Password |

#### `POST /admin/accounts`

创建或更新 Gmail 账号。同一个邮箱重复提交不会创建重复账号，会更新 App Password 和配置。

请求体：

```json
{
  "email": "user@gmail.com",
  "app_password": "xxxx xxxx xxxx xxxx",
  "proxy_mode": "auto",
  "proxy_id": null,
  "sync_enabled": true,
  "sync_interval_seconds": 300,
  "initial_sync_days": 30,
  "initial_sync_limit": 1,
  "remark": "main inbox"
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `email` | 是 | Gmail 邮箱 |
| `app_password` | 是 | Gmail App Password |
| `proxy_mode` | 否 | `auto`、`direct`、`fixed` |
| `proxy_id` | 否 | 选择固定代理；传入后账号会使用 `fixed` |
| `sync_enabled` | 否 | 是否启用同步 |
| `sync_interval_seconds` | 否 | 同步间隔，范围 `60` 到 `86400` |
| `initial_sync_days` | 否 | 搜索最近多少天，范围 `1` 到 `3650` |
| `initial_sync_limit` | 否 | 默认同步数量，范围 `1` 到 `5000` |
| `remark` | 否 | 备注 |

#### `PATCH /admin/accounts/{account_id}`

更新账号配置。所有字段都是可选。

示例：把账号改为直连：

```powershell
curl.exe -X PATCH "http://127.0.0.1:8000/admin/accounts/1" `
  -H "Content-Type: application/json" `
  -d "{\"proxy_mode\":\"direct\"}"
```

示例：改为固定代理：

```powershell
curl.exe -X PATCH "http://127.0.0.1:8000/admin/accounts/1" `
  -H "Content-Type: application/json" `
  -d "{\"proxy_mode\":\"fixed\",\"proxy_id\":1}"
```

#### `POST /admin/accounts/{account_id}/test`

测试账号 App Password、代理和 Gmail IMAP 登录是否可用。

#### `POST /admin/accounts/{account_id}/sync`

触发一次手动同步。

请求体可省略；省略时等同于 `{"limit":1}`。

```json
{
  "limit": 1
}
```

响应为同步任务：

```json
{
  "id": 10,
  "account_id": 1,
  "status": "success",
  "requested_by": "manual",
  "started_at": "2026-07-06T12:31:00",
  "finished_at": "2026-07-06T12:31:03",
  "fetched_count": 1,
  "inserted_count": 1,
  "error": null,
  "created_at": "2026-07-06T12:31:00",
  "updated_at": "2026-07-06T12:31:03"
}
```

#### `POST /admin/accounts/{account_id}/revoke`

清空本地保存的 App Password，禁用同步，并将账号状态设为 `auth_failed`。

### 别名管理

#### `GET /admin/accounts/{account_id}/aliases`

返回某个账号下的所有别名。

#### `POST /admin/accounts/{account_id}/aliases/generate`

按规则生成 Gmail plus aliases。

请求体：

```json
{
  "pattern": "shop-{n:00}",
  "count": 50,
  "label": "shop"
}
```

规则说明：

| pattern | 说明 | 示例 |
| --- | --- | --- |
| `shop-{n}` | 普通序号 | `user+shop-1@gmail.com` |
| `shop-{n:00}` | 两位补零 | `user+shop-01@gmail.com` |
| `shop-{n:000}` | 三位补零 | `user+shop-001@gmail.com` |
| `promo-{rand:5}` | 随机 5 位小写字母和数字 | `user+promo-a8k2z@gmail.com` |
| `promo-{rand:8}` | 随机 8 位 | `user+promo-a8k2z9q@gmail.com` |

如果 pattern 中没有 `{n}` 或 `{rand:N}`，系统会自动在结尾追加序号。

#### `PATCH /admin/accounts/{account_id}/aliases/batch`

批量启用或禁用别名。

```json
{
  "ids": [1, 2, 3],
  "enabled": false
}
```

#### `DELETE /admin/accounts/{account_id}/aliases/batch`

批量删除别名。

```json
{
  "ids": [1, 2, 3]
}
```

#### `DELETE /admin/accounts/{account_id}/aliases/{alias_id}`

删除单个别名。

### 代理管理

代理用于后端连接 Gmail IMAP。账号实际使用代理的优先级：

1. 账号 `proxy_mode=direct`：直连，不使用任何代理。
2. 账号 `proxy_mode=fixed` 且设置 `proxy_id`：使用该固定代理。
3. 账号 `proxy_mode=auto`：优先使用启用的非全局代理池；没有可用代理时使用全局代理；都没有则直连。

#### `GET /admin/proxies`

返回代理列表。代理密码不会明文返回，只返回 `password_configured`。

#### `POST /admin/proxies`

创建代理。

请求体：

```json
{
  "name": "Local SOCKS5",
  "type": "socks5",
  "host": "127.0.0.1",
  "port": 7890,
  "username": null,
  "password": null,
  "enabled": true,
  "is_global": false,
  "timeout_seconds": 20,
  "region": "local",
  "remark": "Clash local proxy"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `type` | `http` 或 `socks5` |
| `host` | 代理主机 |
| `port` | 代理端口 |
| `username` / `password` | 可选认证信息 |
| `enabled` | 是否启用 |
| `is_global` | 是否作为全局代理 |
| `timeout_seconds` | 超时时间，范围 `1` 到 `120` |
| `region` | 区域标记 |
| `remark` | 备注 |

#### `PATCH /admin/proxies/{proxy_id}`

编辑代理。所有字段可选。

```powershell
curl.exe -X PATCH "http://127.0.0.1:8000/admin/proxies/1" `
  -H "Content-Type: application/json" `
  -d "{\"enabled\":true,\"timeout_seconds\":30,\"remark\":\"updated\"}"
```

#### `DELETE /admin/proxies/{proxy_id}`

删除代理。如果有账号固定使用该代理，会自动把这些账号改回 `proxy_mode=auto` 并清空 `proxy_id`。

示例响应：

```json
{
  "ok": true,
  "deleted_id": 1,
  "affected_account_ids": [1, 2]
}
```

#### `POST /admin/proxies/test`

测试一个未保存代理的普通 Web 连通性。

请求体同 `POST /admin/proxies`。

#### `POST /admin/proxies/test-imap`

测试一个未保存代理到 `imap.gmail.com:993` 的 IMAP/TLS 连通性。

请求体同 `POST /admin/proxies`。

#### `POST /admin/proxies/{proxy_id}/test`

测试已保存代理的普通 Web 连通性，并记录测试结果。

#### `POST /admin/proxies/{proxy_id}/test-imap`

测试已保存代理到 `imap.gmail.com:993` 的 IMAP/TLS 连通性。

如果 SOCKS5 代理偶尔可以同步、偶尔报 TLS EOF，通常说明代理节点或规则对 `imap.gmail.com:993` 的 raw TCP/TLS 不稳定。请优先使用 IMAP 测试接口确认代理链路。

### API Key 管理

#### `POST /admin/api-keys`

创建 Consumer API Key。

请求体：

```json
{
  "name": "integration",
  "account_ids": [1],
  "aliases": ["user+shop-01@gmail.com"],
  "ip_allowlist": ["127.0.0.1"],
  "rate_limit_per_minute": 60
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `name` | 名称 |
| `account_ids` | 可访问账号 ID 列表；空数组或省略表示不限账号 |
| `aliases` | 可访问别名列表；空数组或省略表示不限别名 |
| `ip_allowlist` | IP 白名单；空数组或省略表示不限 IP |
| `rate_limit_per_minute` | 每分钟请求数限制 |

#### `GET /admin/api-keys`

返回 API Key 元数据，不返回明文密钥。

#### `PATCH /admin/api-keys/{api_key_id}?active=true`

启用或禁用 API Key。

```powershell
curl.exe -X PATCH "http://127.0.0.1:8000/admin/api-keys/1?active=false"
```

#### `DELETE /admin/api-keys/{api_key_id}`

删除 API Key。删除后该密钥无法再访问 Consumer API。

### 同步任务

#### `GET /admin/sync-jobs`

返回最近 100 条同步任务。

可选查询参数：

| 参数 | 说明 |
| --- | --- |
| `account_id` | 只看某个账号的同步任务 |

示例：

```powershell
curl.exe "http://127.0.0.1:8000/admin/sync-jobs?account_id=1"
```

### 本地邮件管理

#### `GET /admin/messages`

读取本地已同步邮件列表。

查询参数：

| 参数 | 说明 |
| --- | --- |
| `account_id` | 按账号过滤 |
| `alias` | 按别名邮箱过滤 |
| `q` | 搜索主题、发件人、正文 |
| `limit` | 返回数量，范围 `1` 到 `500`，默认 `100` |

#### `GET /admin/messages/{message_id}`

读取本地邮件详情，包括 headers、正文、HTML 和附件元数据。

#### `DELETE /admin/messages/{message_id}`

删除单封本地邮件。

#### `DELETE /admin/messages/batch`

批量删除本地邮件。

```json
{
  "ids": [1, 2, 3]
}
```

示例响应：

```json
{
  "ok": true,
  "deleted_ids": [1, 2, 3],
  "deleted_count": 3,
  "removed_cached_files": 0,
  "file_errors": []
}
```

## Consumer API

Consumer API 面向其它应用读取邮件，需要 `X-API-Key`。

### `GET /api/v1/accounts`

返回当前 API Key 可访问的账号摘要。

示例：

```powershell
curl.exe -H "X-API-Key: mg_xxx" "http://127.0.0.1:8000/api/v1/accounts"
```

响应字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 账号 ID |
| `email` | Gmail 地址 |
| `status` | 账号状态 |
| `last_sync_at` | 最近同步时间 |
| `last_error` | 最近错误 |

### `GET /api/v1/aliases`

返回当前 API Key 可访问的别名列表和统计。

示例：

```powershell
curl.exe -H "X-API-Key: mg_xxx" "http://127.0.0.1:8000/api/v1/aliases"
```

响应字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 别名 ID |
| `account_id` | 所属账号 ID |
| `alias_address` | 完整别名邮箱 |
| `label` | 标签 |
| `enabled` | 是否启用 |
| `message_count` | 命中邮件数量 |
| `last_seen_at` | 最近命中时间 |

### `GET /api/v1/messages`

分页读取当前 API Key 可访问的邮件列表。

查询参数：

| 参数 | 说明 |
| --- | --- |
| `account_id` | 按账号 ID 过滤 |
| `alias` | 按完整别名邮箱过滤 |
| `from` | 按发件人模糊过滤 |
| `to` | 按收件人模糊过滤 |
| `subject` | 按主题模糊过滤 |
| `since` | 只返回该时间之后收到的邮件 |
| `until` | 只返回该时间之前收到的邮件 |
| `has_attachment` | `true` 或 `false` |
| `q` | 搜索主题、摘要、正文 |
| `limit` | 每页数量，范围 `1` 到 `200`，默认 `50` |
| `cursor` | 下一页游标 |

示例：读取最新 20 封：

```powershell
curl.exe -H "X-API-Key: mg_xxx" "http://127.0.0.1:8000/api/v1/messages?limit=20"
```

示例：按别名和关键词搜索：

```powershell
curl.exe -H "X-API-Key: mg_xxx" "http://127.0.0.1:8000/api/v1/messages?alias=user%2Bshop-01%40gmail.com&q=code&limit=20"
```

示例：读取下一页：

```powershell
curl.exe -H "X-API-Key: mg_xxx" "http://127.0.0.1:8000/api/v1/messages?limit=20&cursor=123"
```

响应结构：

```json
{
  "items": [
    {
      "id": 1,
      "account_id": 1,
      "alias_id": 1,
      "alias_address": "user+shop-01@gmail.com",
      "gmail_message_id": "123",
      "thread_id": null,
      "subject": "Your verification code",
      "sender": "service@example.com",
      "recipients": ["user+shop-01@gmail.com"],
      "received_at": "2026-07-06T12:30:00",
      "snippet": "Your code is 123456",
      "has_attachment": false
    }
  ],
  "next_cursor": null
}
```

分页说明：

- 返回按本地 `id` 倒序排列。
- 如果 `next_cursor` 不为 `null`，下一页请求带上 `cursor=next_cursor`。
- 如果 `next_cursor` 为 `null`，说明没有更多数据。

### `GET /api/v1/messages/{message_id}`

读取邮件详情。

示例：

```powershell
curl.exe -H "X-API-Key: mg_xxx" "http://127.0.0.1:8000/api/v1/messages/1"
```

响应在列表字段基础上增加：

| 字段 | 说明 |
| --- | --- |
| `cc` | 抄送地址 |
| `rfc_message_id` | 邮件 RFC Message-ID |
| `history_id` | 同步记录 ID |
| `text_body` | 文本正文 |
| `html_body` | HTML 正文 |
| `raw_headers` | 原始 headers 字典 |
| `attachments` | 附件元数据 |

### `GET /api/v1/messages/{message_id}/attachments/{attachment_id}`

读取已缓存附件内容。

示例：

```powershell
curl.exe -H "X-API-Key: mg_xxx" "http://127.0.0.1:8000/api/v1/messages/1/attachments/1"
```

响应：

```json
{
  "filename": "invoice.pdf",
  "mime_type": "application/pdf",
  "size": 12345,
  "data_base64url": "JVBERi0x..."
}
```

`data_base64url` 是 base64url 编码内容。当前接口只返回已缓存附件；如果附件正文未缓存，会返回 `404` 和 `attachment payload is not cached`。

## 权限和限制

API Key 支持以下限制：

- `account_ids`：限制可访问的账号。
- `aliases`：限制可访问的别名。
- `ip_allowlist`：限制调用来源 IP。
- `rate_limit_per_minute`：限制每分钟请求数。

权限规则：

- 如果 `account_ids` 为空，则不限制账号。
- 如果 `aliases` 为空，则不限制别名。
- 如果同时设置账号和别名，邮件必须同时满足这两个条件。
- 如果请求了无权限的账号或别名，会返回 `403`。
- 如果超过速率限制，会返回 `429`。

## 常见错误

### `401 missing X-API-Key`

调用 Consumer API 时没有传 `X-API-Key`。

### `401 invalid API key`

API Key 不存在、已删除、已禁用，或请求头中的密钥不正确。

### `403 IP not allowed`

API Key 设置了 IP 白名单，但当前请求来源 IP 不在白名单内。

### `403 account not allowed` / `403 alias not allowed`

API Key 没有访问该账号或别名的权限。

### `404 message not found`

本地数据库中没有该邮件。可能原因包括尚未同步、已被本地删除、或 API Key 没有对应可见数据。

### Gmail IMAP TLS EOF

如果同步或账号测试返回类似：

```text
TLS handshake to Gmail IMAP ended early through the proxy
```

通常是代理不支持或不稳定支持 `imap.gmail.com:993` 的 raw TCP/TLS 连接。请使用 `POST /admin/proxies/{proxy_id}/test-imap` 测试，并确认代理类型填写正确。对于本地 `socks5://127.0.0.1:7890`，还需要确认代理规则会把 `imap.gmail.com:993` 走到支持 IMAP TCP/TLS 的节点。
