# 煤炉代购工具

把日本商品候选、中国货源和 Mercari Shops 上架草稿串在一条商品记录里。

## 三个工具部分

1. **日本网站选品**：首批站点为 Mercari、Yahoo!オークション、ラクマ；Yahoo!フリマ和 2nd STREET 已登记为扩展站点。
2. **中国网站找货**：每条闲鱼搜索和货源都关联到原始日本商品，搜索词从日本平台已采集的标题和说明生成；导入闲鱼候选后，工作台自动读取货源详情图并保存为待核对候选。小红书和得物仍可人工添加。上架前由人确认同款、图片实物属性和当前页面价格，不提前采购，也不要求中国货源承诺数量或有效期。
3. **煤炉商品上架**：保存日文标题、商品信息、售价和草稿状态；可记录普通销售或预约销售。发布后登记商品链接。当前不会自动提交发布。

货源图片可以通过 `POST /api/china/sources/{source_id}/images` 上传并记录来源页面、原图链接和图片类型。系统保留来源原图，并生成可用于上架的 JPEG；商品详情会返回两种文件链接。创建上架草稿时，通过 `image_asset_ids` 引用属于该货源的图片，避免图片与商品错配。

收图要求：每件商品至少收集 5 张不同图片，其中必须包含实物图。可从货源详情、评论区、小红书或其他可核验渠道寻找，须核对系列、版本和卡面，并保留每张图片实际来源页面。重复图片或同一张图的不同尺寸不重复计数。第三方实拍与图鉴分开标记，只作为同款及细节参考，不当作当前采购卖家的库存或成色证明；工作台显示图片数量、实物图数量及逐张来源链接。此要求目前用于收图提示，不会阻止保存资料不完整的草稿。

按本项目的业务流程，先建立煤炉上架草稿；日本订单产生后，再按订单数量核对并在中国采购，先发到日本验收，再从日本发给买家。订单记录实付采购价、两段运单、日本收货验收和送达状态。

中国货源数量不用于限制煤炉商品库存。日本订单产生后，再按订单数量重新核对并采购；货源可能在下单前变化，因此采购时仍需确认同款并记录实际采购成本。煤炉自身库存字段和每单限购字段按店铺上架设置单独管理。

当前已实现 Mercari 公开页面关键词搜索、商品详情和参考店铺采集，并可创建关键词 / 店铺监控。Yahoo、ラクマ和小红书、得物的自动采集仍未接入。可选千问视觉 Agent 会比较日本商品参考图与货源候选图，自动决定保留或排除、识别图片类型和实物图概率，并将判断直接应用到图片角色与排除状态。Agent 暂时只接入已有闲鱼图片采集链路；不足 5 张或没有实物图时自动转去小红书 / 得物补搜，仍是后续工作。该功能默认关闭，启用后会把压缩后的货源图片及日本公开参考图链接发送给阿里云 DashScope。店铺浏览器支持临时手动登录、辅助填写草稿和读取订单的任务流程；受登录短信问题影响，登录后的真实页面适配尚待验证，不能视为已经联调完成。正式发布由人在店铺完成。

### 可选：千问图片筛选

在本地 `.env` 配置 `DASHSCOPE_API_KEY` 和 `IMAGE_REVIEW_ENABLED=true` 后，闲鱼图片采集任务会在图片保存后自动调用千问视觉模型，比较日本商品参考图与最多 10 张货源图片，并把结果保存在图片记录中。已有图片也可在货源详情点击“千问筛图”重新处理。模型决定会直接写入图片类型、实物图标记和排除状态；低置信度或缺少结果时默认保留，问题可在上架阶段检查。默认模型为 `qwen3-vl-plus`；可通过 `QWEN_VL_MODEL` 和 `QWEN_VL_BASE_URL` 调整模型与兼容接口地址。禁用功能或未配置 Key 时，图片采集照常完成，不发出模型请求。每次采集或手动复核会按货源发起一次批量视觉请求，最多分析 10 张图，可能产生 DashScope 费用。请将 Key 保存在本地 `.env`，不要提交到版本库或发送到聊天中。

千问使用 OpenAI 兼容的多模态 Chat Completions 接口，支持图片输入；接口说明见[阿里云百炼 Qwen-VL 兼容 OpenAI 文档](https://help.aliyun.com/zh/model-studio/qwen-vl-compatible-with-openai)。

## 本地启动

### Windows

在项目目录的 PowerShell 中执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

脚本会创建独立的 `.venv-win`、安装依赖并启动服务。已有的 macOS `.venv` 不会被覆盖。存在 `.env` 时自动读取配置。Windows 自动化默认使用已安装的 Google Chrome；可通过 `BROWSER_CHANNEL=msedge` 改用 Edge。`BROWSER_HEADLESS=false` 用于可见窗口和手动登录。Linux 使用 Playwright Chromium 时，需执行 `python -m playwright install chromium` 并安装所需系统依赖。

打开 `http://127.0.0.1:8000` 使用中文业务工作台。前端由 FastAPI 直接提供，不需要 Node.js 或单独运行前端服务。

### macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --reload --env-file .env
```

打开 `http://127.0.0.1:8000/docs` 可查看 API 页面。数据库首次启动时自动创建在 `data/coal_store.sqlite3`。

## 业务前端

- **业务概览**：按“日本选品 → 中国找货 → 上架资料 → 订单履约”展示可点击的流程入口、待处理数量与商品动态。
- **商品工作台**：新增日本选品、按阶段筛选、搜索、排序、分页、导出当前筛选结果为 CSV。
- **日本选品**：Mercari 关键词搜索、商品详情和参考店铺采集；查看任务记录、监控及批量资料整理。
- **中国找货**：从日本商品详情发起闲鱼自动搜索；导入候选后会自动读取详情图，并可由千问 Agent 自动判定图片类型、实物图概率和噪声图。现阶段小红书、得物跨平台补图和服装尺码提取尚未实现；当前同款、供货情况和页面价格仍需人工确认。
- **上架资料**：选择货源图片、填写日文文案、分类和配送设置，配置普通 / 预约销售，实时试算利润；可保存通用配送与手续费默认值，新建草稿自动带入且可逐件调整；未发布草稿可编辑，实际发布后登记店铺链接。
- **订单履约**：在订单流程中读取并核对 Mercari Shops 订单，登记成交、实付采购金额、中国到日本物流、日本收货验收、日本境内发货和送达。验收异常可重新登记验收结果。
- **平台目录**：查看日本和中国平台，打开站点继续人工选品或找货。
- **自动化任务**：日本选品页集中查看浏览器任务、监控和资料整理；定时任务最低间隔 60 分钟，只在本应用运行期间执行，停机期间不检查。
- **资料与售后管理**：商品 / 货源编辑、归档及恢复，已上架商品可补充替代货源；订单取消、退货收货、实际退款登记、店铺库存回填和下架登记，保留操作记录。退款接口只登记已发生的退款，不向平台发起转账。

页面不包含演示商品或浏览器本地业务副本，所有业务记录读写现有 SQLite 数据库。空列表、连接失败和保存错误均有对应提示。正式发布仍由人在店铺完成。

`PUT /api/listing/drafts/{draft_id}` 用于修改未发布草稿，使用与创建草稿一致的字段和校验；已发布草稿不可修改。

### 验证

```powershell
.\.venv-win\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv-win\Scripts\python.exe -m unittest discover -s tests -v
```

业务与连接测试使用临时数据库、临时图片和连接替身；另有 2 项可选的独立无头 Chrome 表单及空订单验证（设置 `BROWSER_FORM_TESTS=1` 启用），不写入真实店铺。覆盖业务流程、成本待核算、历史数据迁移、指定店铺连接及填写前确认。真实 Chrome 已验证后台连接与普通商品表单 10 项必填控件读取；最终商品的真实填写、保存以及有订单时的行解析仍待联调。

默认使用工作台专用 Chrome / Edge，由 Playwright 通过本地管道直接控制，不接管日常浏览器，因此正常任务不需要反复点击“允许控制”。首次在专用窗口登录后，Cookie 和站点存储保存在本机 `data/browser_profiles/`，关闭后重开仍可复用，直到平台要求重新登录或安全验证。该目录已加入 Git 忽略；程序不读取或复制日常 Chrome 的登录凭据。

Mercari Shops 设置窗口提供“打开 CDP Chrome 登录窗口”。工作台启动专用 Chrome 配置目录并启用只监听本机的 CDP；人工登录后，在任务结果中点击“已登录，连接店铺”，程序通过 CDP 验证指定店铺并复用会话。登录状态保存在 `data/browser_profiles/japan/shop-login`，店铺地址记录在本地 `data/shop-profile.json`。断开店铺会话不会关闭 Chrome 或清除登录状态。

也可以选择连接日常 Chrome / Edge，但需要用户在浏览器开启远程调试并授权；这与工作台专用的 CDP 登录窗口使用不同的浏览器配置目录。工作台专用登录状态可在服务重启后复用。

闲鱼搜索词从日本平台采集的标题和说明中自动生成，不调用 AI、不要求手填关键词或闲鱼链接。默认在工作台专用浏览器搜索，导入后自动在同一会话采集货源详情图片；搜索、导入和图片任务沿用相同浏览器模式。自动图片保留为待核对候选，不凭页面文字认定实物图，并排除详情页推荐商品流。每条货源最多 10 张图片，每批最多处理 10 条货源。

请从 Windows 正常环境运行 `start.ps1`。专用浏览器使用本机已安装的 Chrome / Edge，默认沿用电脑网络、VPN 和系统代理；也可在 `.env` 设置 `BROWSER_PROXY`、`CHINA_BROWSER_PROXY`、`JAPAN_BROWSER_PROXY`。如果从受网络隔离的工具环境启动，浏览器可能返回 `ERR_NETWORK_ACCESS_DENIED`，此时应修正工作台进程的运行环境，反复授权日常 Chrome 无法解决。

任务可在工作台查看进度、继续或取消。首次登录、平台安全验证或核对表单时需要人工处理。专用会话关闭后保留本地登录状态，临时会话关闭后需重登。平台编辑会自动保存草稿，所以填写任务仍先展示本地资料供核对；正式公开由人在店铺完成。重启后中断任务标记失败，避免重复执行平台操作。

店铺订单先进入待确认区，需要人工核对商品、数量和金额后才创建本地订单。同一导入记录重复确认不会生成重复订单；暂不读取收件人姓名、地址或电话。

升级前建议备份 `data/coal_store.sqlite3` 和同目录的图片文件。本次开发前的 SQLite 一致性备份位于本机 `output/db-backups/`。启动会执行兼容已有记录的表结构迁移。

## API 流程

新增的采集及管理接口可在 `/docs` 查看完整字段：

- `POST /api/japan/search`、`/api/japan/collect/item`、`/api/japan/collect/shop`：创建采集任务，返回任务 ID。
- `GET /api/automation/jobs/{id}`；`POST .../{id}/resume`、`.../{id}/cancel`、`.../{id}/import`：查看、继续、取消任务或导入勾选结果。
- `GET/POST /api/automation/watches`；`PATCH/DELETE /api/automation/watches/{id}`；`POST .../{id}/run`、`.../{id}/restore`；`GET .../{id}/changes`：管理 Mercari 采集监控和定时上架资料整理。归档后恢复默认暂停。
- `POST /api/automation/browser/open`：打开工作台专用浏览器以完成首次登录，任务完成后保持窗口及登录状态。
- `POST /api/automation/shops/cdp-browser/open`：打开隔离的 CDP Chrome 登录窗口并保存店铺连接设置；人工登录后从任务结果连接并接管店铺会话。
- `POST/DELETE /api/automation/shops/session`：连接 / 断开店铺会话。真实浏览器断开后保留窗口与标签。等待中的任务可先取消，再关闭会话。
- `POST /api/listing/drafts/{id}/fill-shop`、`POST /api/automation/shops/read-orders`：填写草稿 / 读取当前订单列表；填写分为资料确认、填表、核对保存两次确认，正式发布手动完成。
- `GET /api/automation/shop-order-imports`；`POST .../{id}/confirm`：核对并关联读取到的店铺订单。
- `PATCH/DELETE /api/items/{id}`；`POST .../{id}/archive`、`.../{id}/restore`：修改、归档和恢复商品。日本商品链接在已有草稿后不可替换；草稿前替换会重置同款核验。
- `PATCH /api/china/sources/{id}`；`POST .../{id}/archive`、`.../{id}/restore`：货源资料管理。已有草稿或订单引用时不能替换货源链接或标题；报价更新不改写历史草稿估价或实付成本。
- `POST /api/orders/{id}/cancellation`、`.../{id}/return-receipt`、`.../{id}/refund-confirmation`：取消、退货收货与退款登记；已发给买家的商品须确认退回后才能取消；退款累计不超过成交金额。
- `POST /api/listing/drafts/{id}/inventory-confirmation`、`.../{id}/withdrawal-confirmation`：回填剩余库存 / 登记已下架。

- `GET /api/japan/sites`、`GET /api/china/sites`：查看站点目录。
- `POST /api/japan/candidates`：登记日本站商品候选。
- `POST /api/china/items/{item_id}/sources`：登记中国站货源候选。
- `GET /api/china/items/{item_id}/sources`：查看商品的中国货源候选。
- `POST /api/china/sources/{source_id}/images`：上传货源实拍、商品图或截图，并记录来源页面。
- `POST /api/china/sources/{source_id}/image-review`：配置并启用千问后，异步复核已有货源图片；只保存建议，不改图片用途或排除状态。
- `GET /api/china/sources/{source_id}/images`：查看货源图片及原图/上架版链接。
- `PATCH /api/china/source-images/{image_id}`：人工核对后更改图片角色，例如确认实物图。
- `GET /api/china/source-images/{image_id}/file?variant=listing`：读取上架版图片；`variant=source` 读取来源原图。
- `POST /api/china/sources/{source_id}/confirm`：人工确认同款，并记录当前页面供货状态和价格；数量承诺和有效期不作为上架前置条件。
- `GET /api/listing/requirements`、`GET /api/listing/items/{item_id}/preparation?source_id=...`、`POST /api/listing/items/{item_id}/preparation`：读取、重新生成上架资料包；确认货源后会自动保存规则版资料。
- `GET/PUT /api/automation/shops/settings`：保存连接方式、浏览器和指定店铺；`POST /api/automation/shops/inspect-form` 只读检查表单。
- `GET/PUT /api/listing/defaults`：读取 / 保存通用上架默认项（配送方式、运费承担方、日本发货地区、发货时效和手续费率）。
- `POST /api/listing/items/{item_id}/drafts`：创建煤炉上架草稿。
- `POST /api/listing/drafts/{draft_id}/publish-confirmation`：人工发布后登记煤炉链接。
- `POST /api/orders`：登记 Mercari Shops 成交订单。
- `POST /api/orders/{order_id}/purchase-confirmation`：订单产生后，记录人工采购来源和实付成本。
- `POST /api/orders/{order_id}/china-shipment`：记录中国发往日本的运单。
- `POST /api/orders/{order_id}/japan-receipt`：记录日本收货与验收结果。
- `POST /api/orders/{order_id}/domestic-shipment`：验收通过后，记录日本发给买家的运单。
- `POST /api/orders/{order_id}/delivery-confirmation`：登记买家已收货。

商品状态为：`candidate → sourcing → matched → listing_draft → listed`。订单履约分段记录：中国采购 `awaiting_purchase → purchased`；中国到日本 `awaiting_dispatch → in_transit → received / inspection_issue`；日本到买家 `not_shipped → shipped → delivered`。同款确认、采购、验收和正式发布都保留人工操作。

利润核算数据保存在本地上架草稿。汇率、中国到日本运费、日本境内运费和其他成本均可留空；只要缺一项就显示“待核算”，不按零成本计算。补齐后自动计算，历史估价保留。

普通商品的必填项及成色、分类、配送控件已按真实店铺表单核对。商品说明、品牌、限购、JAN 和管理码为可选。同款货源确认后，系统按本地记录自动生成并保存规则版资料包；采集与监控页也可新增周期任务，批量整理已核验商品。售价、成色和图片需要核对后再保存店铺草稿，正式发布由人在店铺完成。创建本地草稿至少需要一张选定图片。具体规则见 [上架准备流程](docs/上架准备流程.md)。预约和多规格可保存在本地，但自动填写暂仅支持普通销售、单规格。

### 手工跑通一件商品

在 `/docs` 按顺序调用：登记候选 → 登记中国货源 → 上传并检查图片 → 确认同款和页面价格 → 创建上架草稿并查看预估利润 → 人工发布后登记链接。图片接口接受本地保存的页面图片或截图；请求里要带货源页面链接，可选记录图片直链，并选 `real_photo`、`catalog`、`screenshot` 或 `other` 类型。系统保留原图并生成 JPEG 上架版。创建普通销售草稿需提交图片 ID、商品信息、店铺库存、售价和自动带入的手续费率；汇率及运费估值可稍后补充；只有启用预约销售时才需要预约日期。中国货源数量和有效期不作为草稿门槛。

样例图片位于 `data/examples/hangyodon-xianyu/`，包含闲鱼汉顿商品实拍、JPEG 上架版及来源记录。该图片来自货源帖子，只用于核对图片采集和格式转换流程；它不代表已确认供货或已绑定到数据库记录。

收到订单后登记 `mercari_order_id`、商品和成交价；随后依次确认中国采购、登记中国到日本运单、登记日本收货验收、登记日本到买家运单和送达。验收有问题时订单会进入 `inspection_issue`，不能登记日本境内发货。
