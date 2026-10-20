<div align="right"><b>简体中文</b>&nbsp;·&nbsp;<a href="README.en.md">English</a></div>

# 词蛛 LEXARA

### 一只住在 Windows 桌面上的蜘蛛，用八条腿帮你背单词

> 点它的头 → 框住屏幕上一段英文 → 它趴到文字上，**八条腿各踩住一个单词**，
> 每个词给你音标、中文释义和考纲标签 → 一键收进单词本，按 1 / 3 / 7 / 14 天复习。

![License](https://img.shields.io/badge/license-MIT-1b1f24)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-2f6f4f)
![Python](https://img.shields.io/badge/python-3.13-3b6ea5)
![Offline](https://img.shields.io/badge/OCR%20%2B%20dictionary-100%25%20offline-0e7c7b)
![Dictionary](https://img.shields.io/badge/dictionary-758%2C497%20entries-6b7280)

![八条腿踩住八个单词](docs/screenshots/hero-aim.png)

<p align="center"><sub>真实运行截图：框选后蜘蛛趴到文字上，八条腿分别踩向八个生词，词框颜色 = 踩它的那条腿的颜色。</sub></p>

**全程离线。** 截图、OCR、查词典、复习调度都在本机完成 —— 不上传图片，不需要账号，不内置任何密钥。

**蜘蛛是算出来的。** 8 条步足 + 2 条触须，两骨 IK，阈值驱动步态，逐帧实时解算；没有 sprite sheet，没有骨骼动画文件。

---

## 目录

| | |
| --- | --- |
| [这是什么](#这是什么) | [功能](#功能) |
| [界面](#界面) | [下载与安装](#下载与安装) |
| [用法](#用法) | [数据与隐私](#数据与隐私) |
| [技术实现](#技术实现) | [项目结构](#项目结构) |
| [开发与测试](#开发与测试) | [已知边界](#已知边界) |
| [许可与致谢](#许可与致谢) | |

---

## 这是什么

大部分背单词工具要求你先**离开正在读的东西**：切到 App、拍照、粘贴、等结果。等你回来，读到哪儿已经忘了。

词蛛把这一步压成「不离开屏幕」：蜘蛛就蹲在桌面上，你读到不认识的词，点它的头、把它框住，它自己爬过去把词踩出来。识别、查词、归类、排期全在同一次操作里完成。

它同时是两样东西：

- **一个桌宠** —— 透明置顶、区域点击穿透、会走会跳、能换四套皮肤，不挡你干活；
- **一个识词器** —— 框选即识别，离线 OCR + 75.8 万条词典 + 八档考纲，八条腿把结果直接钉在原文上。

一次识词的完整链路：

```
点蜘蛛的头  →  屏幕冻结变暗，拖框选住一段英文  →  松手
      ↓
离线 OCR（RapidOCR，纯 ONNX，保留词级坐标）
      ↓
挑词：跳过 the / of / because 等虚词 → 词形归一 → 考纲优先 → 表外词兜底
      ↓
蜘蛛爬到词簇正下方，八条腿各踩一个词（够不着的牵一条引导线过去）
      ↓
结果卡：音标 / 释义 / 考纲标签 / 收藏 ☆  →  进入单词本，按 1·3·7·14 天排期
```

---

## 功能

### 识词

| 功能 | 说明 |
| --- | --- |
| 框选即识别 | 全屏冻结截图 + 拖拽选框，Esc / 右键取消，有最小面积保护 |
| 离线 OCR | RapidOCR（纯 ONNX Runtime，模型随包分发），中英文混排；保留行坐标并换算到词级坐标 |
| 多屏与 DPI | 多屏拼接，物理 / 逻辑像素换算，150% 缩放下词框不偏移 |
| 八腿踩词 | 全屏透明覆盖层，8 条腿 ↔ 8 个词的**最小代价分配**；够不着的词只亮引导线，不硬拉成射线 |
| 词框配色 | 每个词框的颜色 = 踩它的那条腿的颜色，一眼看出谁对应谁 |
| 不自动消失 | 结果停在你眼前，点蜘蛛的头或身子才收起（全局低级鼠标钩子）；覆盖层鼠标穿透，期间仍可操作其他窗口 |
| 虚词过滤 | the / of / because 之类自动跳过，可关 |
| 考纲八档 | 四级 / 六级 / 考研 / 雅思 / 托福 / GRE / 工业英语 / 全部；优先挑考纲内，表外词标「词表外」 |
| 词形归一 | 复数、时态、比较级先归原形再查表 |
| 置信度下限 | 0~100% 可调，OCR 置信度太低的词直接不出现 |
| 跳过已掌握 | 阶段 ≥3 且对多于错的词不再打扰你 |
| 可选 AI 语境 | 结果卡里每个词一颗按钮，点了才发请求：句中义、搭配、例句 —— **永不发送截图**，只发词 + 词典义项 + 相邻句 |

### 桌宠

| 功能 | 说明 |
| --- | --- |
| 程序化蜘蛛 | 8 步足 + 2 触须，两骨 IK（髋 → 膝 → 脚尖），矩形头胸 + 三点身体链 |
| 阈值步态 | 脚钉在原地，体心偏移超过 30% 腿长才迈步；同时最多 4~6 条腿运动；迈步时脚向髋部收 18%（真抬腿） |
| 无随机抖动 | 落脚点 = 静止位 + 速度前瞻。加了抖动脚会在原地游走，站姿散成一团 |
| 四套皮肤 | 原皮 · 词蛛 / **白跳蛛（默认）** / 像素蛛 / 奶蛛，点击即生效 |
| 皮肤只换头和身 | 腿长、腿根、命中区、步态、窗口尺寸四套完全一致，切换不重建蜘蛛，走路中途换皮也不抽 |
| 形变动画 | 跳跃弧线（蹲 → 起跳 → 空中 → 落地回弹）、摸头、压扁、抖动、冲刺 |
| 点击穿透 | 腿和身体之外不吃鼠标事件，不挡桌面操作 |
| 右键菜单 | 识词 / 单词本 / 皮肤 / 识词设置 / 回到启动台 / 退出 |

### 学习

| 功能 | 说明 |
| --- | --- |
| 单词本 | 搜索、删除、清空、全部收藏；按考纲五分类（四 / 六 / 雅思 / 托福 / 工业英语）+「未分类」兜底 |
| 间隔重复 | 1 → 3 → 7 → 14 天，答对进档、答错退回次日，到期优先 |
| 背单词流程 | 看词回忆 → 揭示答案 → 自评（认识 / 不认识）→ 进度 → 完成页 → 只重练错词 |
| 学习日历 | 53×7 热力图，日 / 周 / 月 / 年四档；**打开天数与打卡天数分开统计**，三色格（灰 / 浅绿 = 扫描 / 深绿 = 复习） |
| 成就 | 7 / 30 / 100 天里程碑 + 全绿成就，一次性持久化，崩溃后可补弹 |
| 导出图片 | 成就卡导出成只含日历的 PNG，可直接发出去 |

### 界面与系统集成

- **启动台**：无边框圆角卡片、自绘标题栏、8 方向边缘缩放；左侧导航（今日复习 / 收藏夹 / 背单词 / 换皮肤 / 设置），右侧玻璃罐里蹲着待部署的那只蜘蛛
- **部署 / 收回时间轴**：点「部署」→ 罐体三档裂纹 → 网裂闪白 → 碎裂 → 蜘蛛爬出落到桌面；右键「回到启动台」→ 蜘蛛被吸回罐中
- **换装面板**：四套皮肤缩略图，点击实时生效，已部署的桌宠同步换
- **设置**：最大识词数 / 最小置信度 / 桌宠大小 / 窗口置顶 / 释义卡开关 / 恢复默认
- **开机自启动**：写当前用户 Startup 目录的快捷方式，幂等、不需要管理员权限，失败会回滚并给原因
- **启动后自动部署**：与自启动是两个独立开关，只在进程启动时触发一次
- **崩溃日志**：faulthandler + 自定义 excepthook → `run.log`
- **AI 对话（可选）**：启动台底部输入框，OpenAI 兼容接口，后台线程可取消；密钥用 Windows DPAPI 加密落盘

---

## 界面

启动台：左边是今日复习与导航，右边玻璃罐里是待部署的蜘蛛，底部是「部署」。

![启动台](docs/screenshots/launcher.png)

换装面板：四套皮肤，点一下立刻生效，桌面上那只同步换。

![换装面板](docs/screenshots/skins.png)

步态由几何实时解算 —— 下面五帧是同一个引擎在跑 idle、行走、跳跃时的真实渲染（不是逐帧动画素材）：

![步态五帧](docs/screenshots/gait.png)

成就导出：日历热力图 + 里程碑，导出为只含日历的 PNG（图为作者本机真实数据，107 天）。

![成就导出](docs/screenshots/calendar.png)

---

## 下载与安装

两条路，任选一条。**都不需要账号，都不需要联网激活。**

| | 路线 A · 直接运行 | 路线 B · 自行配置 |
| --- | --- | --- |
| 适合 | 只想用 | 想改代码 / 不想下来历不明的 exe / 要接自己的模型 |
| 前置 | 无 | Python 3.13 x64 |
| 体积 | 单文件约 150 MB | 首次装依赖约 300 MB |
| 启动 | 首次 10~20 秒（解压内置词典），之后快 | 略快 |
| 更新 | 重新下 exe | `git pull` |

### 路线 A · 直接运行 exe

1. 到 [Releases](../../releases) 下载 `Lexara.exe`；
2. 双击它。**不需要装 Python，不需要装任何运行库**；
3. 第一次可能弹「Windows 已保护你的电脑」—— 这个 exe 没有买代码签名证书（个人项目，证书一年几百美元），点「更多信息」→「仍要运行」，之后不再提示；
4. 首次启动会先把内部文件（含 75.8 万条词典）解压到临时目录，约 10~20 秒，之后再启动就快了；
5. 启动台打开后，点右下角「部署」，蜘蛛落到桌面右下角。

> exe 不在仓库里 —— 单文件 150 MB 不适合放进 Git 历史，只作为 Release 附件提供。仓库里是纯源码。

- 系统要求：**Windows 10 / 11，64 位**（只支持 Windows，原因见[已知边界](#已知边界)）
- 不需要管理员权限，不写注册表，不装后台服务，不建计划任务
- 卸载：删掉 exe，再删 `%APPDATA%\Lexara` 整个目录

> 杀毒软件偶尔会报毒。PyInstaller 单文件 exe 的自解压行为很像打包器，属于常见误报；不放心就用路线 B 从源码跑，或者直接读源码。

### 路线 B · 自行配置（源码运行）

**前置条件**：Python **3.13**（64 位），安装时勾选 `Add python.exe to PATH`。3.12 及更早版本未验证，建议直接装 3.13。

```bash
git clone https://github.com/<your-name>/lexara.git
cd lexara
```

**第 1 步 · 建环境、装依赖（一键）**

双击 `install_first.bat`。它会：找到 Python → 建 `.venv` → 升级 pip → 按 `requirements-runtime.txt` 装运行期依赖。重复运行是安全的（已有 `.venv` 就复用）。

**第 2 步 · 启动**

双击 `run.bat`。它会自动找 `.venv`（找不到会退回系统解释器），然后跑 `src/main.py`。

想带参数（比如自检并逐帧截图）：

```bat
run.bat --selftest
```

**第 3 步 · 部署**

启动台里点「部署」。

#### 手动安装（不想用 .bat，或要用 IDE）

```bat
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python src\main.py
```

`requirements.txt` 比 `requirements-runtime.txt` 多一个 PyInstaller（只有打包时才需要）。依赖清单：

```
PySide6-Essentials == 6.12.0      # Qt 6 + QtQuick（不需要 Addons）
shiboken6          == 6.12.0
rapidocr_onnxruntime == 1.2.3     # 离线 OCR
onnxruntime        == 1.31.0
opencv-python      == 5.0.0.93
numpy              == 2.5.4
pyinstaller        == 6.22.3      # 仅打包
```

#### 国内装依赖太慢

换镜像重装（`.venv` 已建好的话只跑这一行）：

```bat
.venv\Scripts\python -m pip install -r requirements-runtime.txt ^
    -i https://pypi.tuna.tsinghua.edu.cn/simple
```

#### 装不上 / 起不来，先看这张表

| 现象 | 原因与处理 |
| --- | --- |
| `No Python interpreter found` | Python 没进 PATH。重装并勾选 `Add python.exe to PATH`，或命令行里手动指定 `py -3.13` |
| pip 卡住 / 大量超时 | 国内直连 PyPI 慢。用上面的镜像命令；公司网络需要代理时先设 `HTTP_PROXY` / `HTTPS_PROXY` |
| `opencv-python` 装不上 | 多半是 Python 版本或位数不对（要 64 位 3.13），也可能是没对应平台的轮子 |
| 双击 `run.bat` 闪退 | 在命令行里跑 `run.bat` 看报错；再到 `%APPDATA%\Lexara\run.log` 看最后几十行 |
| 界面出来了但蜘蛛不出现 | 点启动台右下角「部署」；或右键托盘图标 → 显示桌宠 |
| 蜘蛛跑到屏幕外 | 右键菜单里重置位置，或删 `%APPDATA%\Lexara\settings.json` 重启 |

> 两个 `.bat` 必须保持**纯 ASCII**。cmd 会先用 OEM 代码页解码整份脚本，插入任何中文都会让每一行解析失败 —— 这个坑项目里踩过，所以中文说明都在本文件里。

#### 可选：接自己的 AI（默认关闭）

主功能**完全不需要联网、不需要密钥**。只有启动台底部的对话式 AI 和「AI 语境分析」需要你自己指定服务（OpenAI 兼容接口）。

**方式一 · 界面里填**

启动台 → 设置 → AI 模型右侧「去配置」→ 填 Base URL / 模型名 / 密钥 → 保存。密钥用 **Windows DPAPI** 加密后写进 `%APPDATA%\Lexara\ai_secret.bin`，只有当前 Windows 账户解得开。

**方式二 · 环境变量**

```bat
setx LEXARA_AI_API_KEY "sk-..."
setx LEXARA_AI_URL     "https://api.openai.com/v1"
setx LEXARA_AI_MODEL   "gpt-4o-mini"
```

重开终端 / 重开程序生效。优先级：**界面里存的 > 环境变量**。地址填 Base URL 会自动补 `/chat/completions`，也可以直接填完整地址；本机跑模型允许 `http://localhost:端口`，公网非 HTTPS 会被拒。

#### 可选：自己打成 exe

```bat
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m PyInstaller Lexara.spec
```

产物在 `dist\Lexara.exe`。也可以双击 `tools\build_exe.bat` —— 它会**先跑完所有测试再打包**，测试不过就不出包。

仓库里有 5 个 `.spec`：`Lexara`（正式）/ `LexaraDebug`（带控制台）/ `LexaraFixed` / `LexaraPortable` / `LexaraPortableDebug`。结构一致，只有 `name`、`console`、`onefile` 不同。

---

## 用法

| 操作 | 效果 |
| --- | --- |
| **点蜘蛛的头**（矩形头胸那一端） | 开始框选识词 |
| **Ctrl + Shift + S** | 快速框选（不用先找蜘蛛） |
| **双击** | 同样框选识词 |
| **按住拖动** | 移动蜘蛛（八条腿按阈值步态小跑） |
| **单击身体** | 随机互动：跳 / 压扁 / 抖动 / 冲刺 |
| **滚轮** | 放大 / 缩小（持久化） |
| **右键** | 功能菜单 |
| **识词之后** | 点蜘蛛的头或身子收起瞄准层；点词框或结果卡看释义、收藏 |

**只点蜘蛛的头或身子才会收起瞄准层**；点屏幕其他地方既不收起也不吞事件（覆盖层是鼠标穿透的），你可以继续操作别的窗口。

虚词自动跳过，优先挑考纲内的词；结果卡里点 ☆ 收藏，或「全部收藏」。收藏后进入单词本，下一次复习按间隔自动排期。

见[界面](#界面)一节的热力图：灰色 = 没有学习活动，浅绿 = 当天至少扫过一次词，深绿 = 背过单词或主动用过 AI。

---

## 数据与隐私

| 项 | 位置 | 说明 |
| --- | --- | --- |
| 词典 | 内置 `assets/ecdict.sqlite` | ECDICT Revised v0.1.1，**758,497** 条，只读 |
| 考纲标签 | 内置 `assets/exam-tags.sqlite` | 14,942 词，与词典解耦，可单独更新 |
| 设置 | `%APPDATA%\Lexara\settings.json` | 皮肤、考纲、识词数量、置信度…… |
| 单词本 | `%APPDATA%\Lexara\wordbook.json` | 收藏 + 复习进度；**原子写**，断电不会写坏；旧版本数据可直接读 |
| 主题 | `%APPDATA%\Lexara\theme.json` | |
| 运行日志 | `%APPDATA%\Lexara\run.log` | 出问题先看它 |
| AI 密钥 | `%APPDATA%\Lexara\ai_secret.bin` | 仅在你配置过之后才有；DPAPI 加密，换 Windows 账户读不出来 |

- **截图不出机器。** 框选的是本机屏幕，OCR 在本机 ONNX 模型上跑，识别完的临时图不落盘。
- **没有账号、没有云同步、没有遥测。** 整份程序里没有任何上报端点。
- 想备份单词本 = 拷走 `wordbook.json`；想恢复出厂 = 删掉 `%APPDATA%\Lexara` 整个目录。

---

## 技术实现

### 两阶段交互

```
启动台 Launcher (QML)  ──「部署」──▶  桌宠 Pet (Qt Widgets)  ──框选──▶  瞄准层 AimOverlay
        ▲                                    │
        └──────────「回到启动台」收回──────────┘
```

启动台是「养蜘蛛的地方」，桌宠是「干活的蜘蛛」。两者是同一个进程里的两个窗口，共用一份 `settings.json`。

### 选型

| 层 | 选型 | 为什么 |
| --- | --- | --- |
| 语言 | Python 3.13 | 全部业务逻辑 |
| GUI | PySide6 6.12（Qt 6） | 两套并存：Qt Widgets + Qt Quick/QML |
| 渲染 | `QPainter` 逐帧自绘 | 蜘蛛、玻璃罐裂纹、热力图、词框全部代码绘制，不用贴图动画 |
| 启动台 | QML + Python 桥接 | `src/qml/Main.qml` + `src/launcher_qml.py` |
| 桌宠 / 瞄准层 | Qt Widgets（自绘 + 区域遮罩） | 全透明置顶 + 鼠标穿透，Widgets 比 QML 稳 |
| OCR | RapidOCR 1.2.3（纯 ONNX） | 离线、中英文、模型随包分发、保留坐标 |
| 词典 | SQLite（ECDICT 全量） | 只读连接，`threading.local` 管理，不阻塞 UI |
| 打包 | PyInstaller 6.22 | 单文件 exe，Qt 与 OCR 模型内嵌 |

刻意**没有**引入 Web 技术栈：桌宠需要「全透明 + 置顶 + 区域穿透点击 + 60fps 自绘」，用 `QPainter` 比套一层 WebView 便宜得多，打包时还显式排除了 `QtWebEngine`。

### 几个关键点

<details>
<summary><b>步态是移植的，不是编的</b></summary>

`STEP_FRAC=.3 / URGENT_FRAC=.5 / OVER_FRAC=.92 / PLACE_FRAC=.85`、
`LEAD_SECONDS=.3 / LEAD_MAX_FRAC=.3`、迈步时长 0.10~0.17 秒、抬腿幅度 18%，
全部对齐 `crawler.js` 的 `T` 对象。

落脚点是「静止位 + 速度前瞻」，**没有随机抖动** —— 加了抖动脚就会在原地游走，站姿散成一团。
</details>

<details>
<summary><b>身体位移必须喂给步态引擎</b></summary>

脚钉在原地，身体一动，静止位就相对偏移，偏移超过阈值才迈步。桌宠每帧把体心的屏幕位移传给
`Spider.update(..., motion=...)`；不喂位移，腿会一直站着不动。
</details>

<details>
<summary><b>窗口遮罩跟随实时腿位</b></summary>

如果按静止站姿建遮罩，迈步中的腿会伸出遮罩被裁掉，表现为「腿没了只剩脚点」。
因此遮罩限频（约 12 Hz）按当前 hip / knee / tip 重建。
</details>

<details>
<summary><b>OCR 坐标不翻倍</b></summary>

小图放大后如果直接乘缩放系数，词框会整体偏移一倍。`test/test_ocr_coords.py`
专门守这条回归：坐标只在「原图坐标系」里算，缩放只发生在最后一步绘制。
</details>

### 规模

- 源码 **33 个 Python 模块 + 1 个 QML**，约 **25,700 行**
- 词典 758,497 条，考纲 14,942 词，八档筛选
- 单文件 exe 约 150 MB（内含 Qt、OCR 模型、词典），冷启动首次解压 10~20 秒
- 空闲超过 8 分钟自动卸载 OCR 模型（常驻约 90 MB），下次识词自动重建

---

## 项目结构

```
lexara/
├── src/
│   ├── main.py                 入口（--selftest 自检截图 / --ocr-test 链路测试）
│   ├── crawler_spider.py       程序化蜘蛛：几何 + 两骨 IK + 阈值步态 + 腿↔词分配
│   ├── spider_painter.py       QPainter 渲染
│   ├── aim_overlay.py          八腿踩词的全屏瞄准层
│   ├── capture.py              冻结桌面 + 框选（多屏 + DPI 换算）
│   ├── ocr_engine.py           RapidOCR 封装，保留词级坐标
│   ├── ocr_registry.py         识别引擎注册表（真实探测可用性）
│   ├── lexicon.py              ECDICT 全量查询 + 考纲标签 + 挑词
│   ├── wordbook.py             收藏 + 间隔重复调度
│   ├── review_session.py       复习会话（QML 与 Widgets 共用，不分叉）
│   ├── activity.py             学习日历事件与统计
│   ├── calendar_export.py      成就导出 PNG
│   ├── pet_window.py           桌宠窗口（状态机 / 交互 / 托盘）
│   ├── launcher_qml.py         启动台 QML ↔ Python 桥接
│   ├── dialogs.py              结果卡 / 单词本 / 设置
│   ├── settings_store.py       设置原子写
│   └── qml/Main.qml            启动台界面
├── test/                       单元测试
├── tools/                      截图 / 渲染诊断 / 打包 / 自检脚本
├── assets/                     词典、考纲、皮肤、图标、音效
├── docs/screenshots/           本 README 的截图
├── install_first.bat           一键建 .venv + 装依赖
├── run.bat                     启动
└── *.spec                      5 份 PyInstaller 配置
```

---

## 开发与测试

```bat
.venv\Scripts\python tools\run_tests.py       :: 统一入口，出 PASS/FAIL 表
.venv\Scripts\python test\test_spider.py      :: 蜘蛛几何 / 步态（33 项）
.venv\Scripts\python src\main.py --selftest   :: 自检并逐帧截图
```

| 步骤 | 内容 |
| --- | --- |
| 单元测试 | **16 个测试文件**：蜘蛛几何 / 腿伸展 / 点击穿透 / OCR 坐标 / 行业词库 / 折叠模式 / 瞄准保持 / 旋转动画 / 皮肤 / 连续扫词队列 / 词框贴合 / 复习会话 / AI 配置与密钥安全 / OCR 引擎注册表 / 线程 OCR / AI 基础 |
| 端到端 | `tools/aim_e2e.py` —— 腿真的落在词上、词框不越界（19 项） |
| 触发矩阵 | `tools/aim_trigger_probe.py` —— 什么情况下该触发瞄准（13 项） |
| 桥接自检 | `tools/qml_bridge_probe.py` —— 设置真的写回 settings / 渲染器 / payload（13 项） |
| UI 自检 | `tools/ui_probe.py` —— 背单词全流程、AI 配置与安全存储、引擎真实状态、帮助文案一致性 |
| 打包 | `tools/build_exe.bat` —— 9 步，测试不过不出包 |

调试用环境变量：

| 变量 | 作用 |
| --- | --- |
| `LEXARA_QML_SHOT=<path>` | 启动 2.6 秒后自动截图退出（README 里的启动台截图就是这么拍的） |
| `LEXARA_QML_PANEL=skins\|settings` | 启动时直接展开某个覆盖面板 |
| `LEXARA_LEGACY_LAUNCHER=1` | 回退到旧的 Qt Widgets 启动台 |
| `LEXARA_MEM_TRACE=1` | 打印进程内内存占用（测内存别用外部采样，会量到启动器空壳） |

会写盘的脚本遵循同一条约定：**临时 profile + 摘掉 `LEXARA_AI_*` 环境变量**，不碰用户词库与密钥。

---

## 已知边界

写在这里，是因为「看起来能点」不等于「功能完整」。

**已经能用，有测试覆盖**

- 框选 → OCR → 挑词 → 八腿踩词 → 结果卡 → 收藏 → 间隔重复，整条链路
- 桌宠全部交互（拖动 / 缩放 / 随机互动 / 右键 / 点击穿透）
- 四套皮肤即切即生效，启动台与桌宠双向同步
- 启动台部署 / 收回完整时间轴
- 设置持久化、开机自启动、启动后自动部署
- 学习日历与成就导出、按考纲分类的收藏夹
- QML 背单词流程（真写回 1/3/7/14 调度）
- 单文件 exe 打包与冷启动

**明确没做**

- 多用户 / 云同步 / 账号体系（纯本地单机）
- 移动端、macOS、Linux —— 大量 Windows 专有 API：`WH_MOUSE_LL` 全局鼠标钩子、DPI 换算、DPAPI 密钥加密、Startup 目录，换平台要另做安全存储方案
- 「蜘蛛感应」式持续自动扫描（帮助面板里如实标着「规划中」）
- 拼写 / 听力题型，当前只有「看词回忆 + 自评」一种
- AI 对话是**非流式**的，界面如实显示「请求中」，不假装在打字

**验证范围**

- 高 DPI：开发机是单屏 150% 缩放，全部截图与探针都在 150% 下通过；100% / 125% 用 `QT_SCALE_FACTOR` 模拟验证过布局，**真机 100%/125% 与多屏负坐标未实测**

---

## 许可与致谢

**本项目的程序代码与自绘素材采用 [MIT 许可证](LICENSE)。**

用到的开源项目与数据（完整清单、版本与许可全文见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 与 `licenses/`）：

| 项目 | 用途 | 许可 |
| --- | --- | --- |
| [RapidOCR](https://github.com/RapidAI/RapidOCR)（`rapidocr-onnxruntime` 1.2.3） | 离线 OCR | Apache-2.0 |
| [ECDICT Revised](https://github.com/sliuhaob/ecdict-revised) v0.1.1（基于 [skywind3000/ECDICT](https://github.com/skywind3000/ECDICT)） | 内置词库 758,497 条 | MIT + CC BY-SA 4.0 |
| [web-crawlers](https://github.com/cyohei9907/web-crawlers) | 八足几何与步态的移植来源（Python 重写，未分发其源码） | **未声明** |

**PySide6 / Qt 6 是 LGPL-3.0。** 本项目用 PyInstaller 打包分发，Qt 库内嵌在可执行文件中；按 LGPL 要求，源码与 5 份 `.spec` 一并提供，任何人都可以用自己修改过的 Qt 重新打包。许可证全文见 `licenses/LGPL-3.0.txt`。

> **关于 `web-crawlers` 的一条实话**：`src/crawler_spider.py` 与 `src/spider_painter.py` 的几何与步态移植自该项目，而上游仓库**尚未声明许可证**。在对方补充许可之前，这两个文件不能被当作干净的 MIT 代码再分发。其余代码与素材不受影响。素材归属：`jar_crack_*` 由 `spider_cracked.png` 派生，`lexara_logo*` 与 `icon.*` 由 `tools/` 下的脚本程序化生成。
>
> `assets/ecdict.sqlite` 是第三方数据，按上游双许可分发，**不适用**本项目的 MIT 许可。

---

<div align="center">
<sub>词蛛 LEXARA · Windows 桌面学习工具 · <a href="README.en.md">English</a></sub>
</div>
