# supermarkt-angebote（超市特价面板）

Elliot 的个人工具：每天抓取慕尼黑 80995 附近 EDEKA、REWE、ALDI SÜD、Kaufland、Lidl 的每周特价，只保留关心的几类食品，生成手机网页。

- 远程：https://github.com/Elliot011019/supermarkt-angebote（公开，main）
- 网页：https://elliot011019.github.io/supermarkt-angebote/（GitHub Pages，main 的 /docs）

## 架构
- `config.yaml`：类别定义（queries / include / exclude / exclude_words / exclude_desc / exclude_categories）。**调匹配只改这个文件。**
- `fetch.py`：调用 marktguru 非官方接口 `api.marktguru.de/api/v1/offers/search`（关键词 + 邮编）。key 运行时从 marktguru.de 首页 `<script type="application/json">` 读取，可用 `MG_API_KEY` / `MG_CLIENT_KEY` 覆盖。流程：识别超市 → 按类别过滤 → 去重 → 写 `docs/data.json`。
- `nutrition.yaml`：每类商品每 100 g 的参考营养值（USDA / BLS 同类取整）和增肌减脂等级规则（A–E，按蛋白供能比，低蛋白时再看脂肪供能比）。fetch.py 给每条特价加 `nut` 字段；运行日志会列出“没有营养规则”的商品，看到就补规则。
- `docs/index.html`：静态页，读 data.json。按类别 / 按超市两个视图；按单价 / 折扣 / 价格排序；隐藏过期特价；未开始的标“X月X日起”；App 专享价单独标出；商品名后显示营养等级，可按营养等级排序。
- `.github/workflows/update.yml`：每天 04:00 UTC 跑 fetch.py，data.json 有变化就自动提交。**远程会不断出现 github-actions 提交，推送前必须 `git pull --rebase`。**
- 失败设计（不要破坏）：抓取失败不覆盖旧数据并以非零退出（GitHub 发邮件）；页面数据超过 48 小时未更新会提示。

## 已定需求（不要擅自改）
- 只要这 5 家超市；Netto、PENNY 明确不要。
- 类别：Skyr、牛肉、羊肉、鸡肉（不含火鸡）、橘子（含橙子，不含橙汁等加工品）、香蕉、莓果（不含冷冻）、披萨。
- 莓果、香蕉的 include 只用复数（Erdbeeren、Bananen）：鲜果用复数，口味 / 零食用单数，可挡掉大部分误判。
- 去重键：超市 + 名称（去非字母、小写）+ 品牌 + 价格 + 截止日期（REWE / EDEKA 把同一特价放进多份区域传单，ID 不同）。
- 无品牌占位符 `thisisnobrand123` 要清洗掉。
- App 专享价：`requiresLoyalityMembership` 字段 + 描述里的 "HINWEIS: MIT … APP" 类文字。
- 鸡肉加工品：Hähnchen-Rouladen（填馅鸡肉卷）和 Suppentopf（汤锅）不要；裹粉鸡排、腌制鸡排、冷冻鸡排保留（营养等级会标低）。

## 工作规则
- 不用 force push；rebase 冲突先停下来问。`docs/data.json` 冲突以远程为准。
- 不索取、保存或打印任何 token / 密码。
- 调关键词：`python3 fetch.py --dump` → 看 `raw.json` 原始商品名 → 只改 config.yaml → 本地重跑对比“各类别”计数，说明剔除了什么、有无误伤。
- 抓取报错多半是 key 获取失败或接口结构变了：先 `--dump` 看原始返回再修，不要猜。
- 非官方接口，仅个人使用：请求间保留 `time.sleep(1)`，不增加频率。
