# 安全规范（Security）

## 1. 密钥与配置

- `SECRET_KEY` 必须在部署/共享环境自定义；禁止提交真实密钥到 git。
- **第三方 API 密钥（如 OpenAI 兼容服务）**：必须仅保存在本机环境中，严禁硬编码或提交至代码库。  
- 默认占位密钥：启动应告警（已有逻辑需保持）。  
- 配置文件：`~/.config/inquisitive/backend.env`、`frontend.env`。

## 2. 认证与授权

- 密码哈希与 JWT 交给 fastapi-users 既有方案，不自写明文密码。  
- JWT 过期时间保持合理默认；可用配置覆盖。  
- **授权**：用户只能访问自己的 Note/File/Link/Job/向量切片。  
- 未来 workspace：所有 search/chat 必须带 workspace 作用域并校验 membership。

## 3. 上传

- 后端强制：扩展名白名单 + 大小上限（`ALLOWED_UPLOAD_EXTENSIONS`、`MAX_UPLOAD_BYTES`）。  
- 前端白名单必须与后端对齐，**以后端为准**。  
- 文件名消毒，防止路径穿越。  
- 不信任客户端 Content-Type 作为唯一安全依据。

## 4. 出站请求（链接抓取）

- 存在 SSRF 风险（抓取用户提供 URL）。  
- 最低要求（渐进）：超时、体积限制、合理 User-Agent。  
- 强化（规划）：屏蔽链路本地/内网地址、重定向策略。

## 5. CORS 与网络暴露

- 开发默认宽松 CORS 可以；暴露到局域网/公网前收紧 `CORS_ORIGINS`。  
- 公网部署：HTTPS 反代、改密钥、限制注册（`ALLOW_AUTO_USER_REGISTER` 等）。

## 6. 日志与隐私

- 日志避免完整 token、密码、大块正文 dump。  
- 错误返回不包含服务端绝对路径中的敏感主目录细节（尽量）。

## 7. 许可证

- 代码许可 **AGPL-3.0**。  
- 网络提供修改版服务时注意源码义务。  
- 规范与 README 不将许可证表述为 MIT/专有。

## 8. 安全相关改动检查清单

- [ ] 新接口是否挂了鉴权？  
- [ ] 查询是否过滤 user_id（或 workspace）？  
- [ ] 上传/路径是否校验？  
- [ ] 是否引入新的默认密钥或 debug 后门？  
- [ ] 向量删除是否可能漏删导致他用户可见？（过滤条件）
