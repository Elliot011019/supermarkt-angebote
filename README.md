# 超市特价面板

每天自动抓取 EDEKA、REWE、ALDI SÜD、Kaufland、Lidl 在邮编 80995 附近的特价，
只保留你关心的类别，做成一个手机上随时能打开的网页。

- `config.yaml`：类别和关键词，改这里就行
- `fetch.py`：抓取和过滤
- `docs/index.html`：网页
- `docs/data.json`：数据（现在是示例数据，第一次运行后自动替换）
- `.github/workflows/update.yml`：每天自动运行

## 部署（约 10 分钟）

1. **建仓库**：GitHub 上新建一个仓库（免费账号用 GitHub Pages 需要 public 仓库），把这个文件夹的全部内容传上去。
   注意 `.github` 是隐藏文件夹，Mac 的 Finder 里按 Cmd+Shift+. 才能看到；用网页上传时别漏了它。用 `git push` 最省事。
2. **给自动任务写权限**：仓库 Settings → Actions → General → Workflow permissions，选 *Read and write permissions*，保存。
3. **手动跑第一次**：Actions 标签页 → “更新特价数据” → Run workflow。跑完点进去看日志，应该看到“写入 N 条特价”。
4. **开网页**：Settings → Pages → Source 选 *Deploy from a branch*，分支 `main`，文件夹 `/docs`，保存。
   一两分钟后打开 `https://你的用户名.github.io/仓库名/`。手机上可以“添加到主屏幕”。

之后每天早上自动更新，不用管。

## 出问题时

- **抓取失败**：GitHub 会发邮件通知你；网页上也会提示“数据已经 N 天没更新”。旧数据不会被清空。
- **最可能的原因是密钥获取失败**。手动设置：电脑浏览器打开 marktguru.de，按 F12 → Network，在网站上随便搜一个商品，
  找到发往 `api.marktguru.de` 的请求，在 Request Headers 里复制 `x-apikey` 和 `x-clientkey` 的值，
  然后到仓库 Settings → Secrets and variables → Actions，新建 `MG_API_KEY` 和 `MG_CLIENT_KEY` 两个 secret。
- **某类东西匹配得不对**（漏了或混进无关商品）：本地运行 `python fetch.py --dump`，看 `raw.json` 里原始商品名，再调整 `config.yaml` 的关键词。
- **某家超市一直是 0 条**：看运行日志最后一行“其他商家（已忽略）”，如果那家超市的名字写法不一样，改 `fetch.py` 顶部的 `STORES`。

## 说明

数据来自 marktguru 的非官方接口，仅适合个人使用；接口随时可能变，需要偶尔维护。
