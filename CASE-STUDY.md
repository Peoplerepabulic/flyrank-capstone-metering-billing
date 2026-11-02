# LLM Usage Metering & Billing Service — 案例研究

FlyRank Backend AI Engineering 方向 Capstone C4 · FastAPI 服务 · 仓库：https://github.com/Peoplerepabulic/flyrank-capstone-metering-billing

## 1. 问题

一个对外提供 LLM 调用的 SaaS 必须准确回答三个问题：这个客户用了多少、该收多少钱、有没有触到套餐上限。难点不在基础设施，而在正确性：客户端重试不能重复计费；配额边界必须明确，不能含糊；不同类别的 token 定价规则不同；订阅状态变化必须先于配额判断，否则已欠费或已取消的租户仍会被计费。

## 2. 做了什么

用 FastAPI 构建了一个用量计量与计费服务，核心是 `POST /v1/generate` 与 `GET /v1/usage`：

- **恰好一次计量**：`Idempotency-Key` 为必填请求头；同一租户、同一 key 的重试直接返回原始响应，不重复记账，数据库以 `UNIQUE(tenant_id, idempotency_key)` 作为兜底。
- **明确的配额边界**：规则为 `current + requested <= limit` 才放行；恰好触到上限的请求成功，下一条返回 429（配额耗尽，提示升级）；订阅为 past_due 或 canceled 时先返回 402。套餐为 Free（每月 1,000 次调用 / 100,000 token，$0）与 Pro（每月 100,000 次调用 / 10,000,000 token，$49/月）。
- **整数金额计算**：所有金额以整数 microdollar 存储，展示时四舍五入到分；定价钉在配置中：input $1.50/1M token、cached input $0.75/1M、output $6.00/1M，reasoning token 按 output 计价，各类别分开计价、绝不先求和再定价。
- **订阅计费**：Stripe 风格的 webhook（`checkout.session.completed`、`customer.subscription.updated`、`customer.subscription.deleted`），先验签、再按 event id 去重，最后同步租户套餐与状态；默认使用内置模拟 provider，真实 Stripe 仅在 test mode 且配置密钥时启用，不涉及真实资金。
- **后台任务**：每小时对账（数据库与 provider 视图不一致即告警）与配额监测（80% 提醒、100% 耗尽），默认 SQLite，可通过 `DATABASE_URL` 切到 Postgres。

验证方式写进了仓库：13 个测试 + 5 个验收探针，探针输出见 `EVIDENCE.md`，设计见 `DESIGN.md`。诚实边界：默认计费走模拟器，不含发票、分期摊销与超量计费，这些是明确的非目标。

## 3. 结果

2026-10-02，FlyRank 门户将该 Capstone 标记为 Approved / Accepted，未被退回。评审人 Alen Malkocon 的异步评审（AI 辅助）肯定了两点：按租户归属的幂等设计，以及精确的配额边界。

它证明的是：我能把“钱相关”的后端做成可验证的——重试不重复计费、边界行为可复现、金额计算不用浮点数。
