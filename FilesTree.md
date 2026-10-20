# 词蛛LEXARA · 项目结构（FilesTree）

> 项目原名「八足微光」，2026-10-16 正式改名 **词蛛LEXARA**。
> 一个全离线的桌面英语学习宠物：程序化蜘蛛 + 框选识词 + 间隔复习。
> 源码 `src/` 16 个模块共 **9,248 行**，测试 10 套件 **276 项**，工具脚本 23 个。

```
八足微光/                                （项目根，即 词蛛LEXARA）
│
├── run.bat                              一键启动（开发环境，免打包直接跑 src/main.py）
├── Lexara.spec                          PyInstaller 打包配置（单文件 exe）
├── README.md                            项目说明（皮肤系统、开发约定）
├── HANDOFF.md                           交接文档：按时间倒序记录每一轮改了什么、为什么、怎么验收
├── 项目介绍.md                          项目方向介绍（解决什么问题 / 演示什么效果）
├── FilesTree.md                         本文件
├── src.zip                              src 快照（历史留档）
│
├── src/                                 ★ 源码：16 个模块，9,248 行
│   ├── main.py                  (705)   程序入口：启动台/桌宠生命周期、崩溃日志、改名数据迁移
│   │
│   │  ── 界面层 ──
│   ├── launcher_window.py      (2194)   启动台：词表/皮肤/收藏/部署动画（全项目最大，含玻璃罐）
│   ├── pet_window.py           (1587)   桌宠主窗口：拖动/缩放/右键菜单/识词链路/托盘
│   ├── aim_overlay.py           (599)   全屏瞄准层：八腿踩词、词框辉光、全局鼠标钩子、腿长按需拉伸
│   ├── capture.py               (229)   全屏框选遮罩（选区橡皮筋）
│   ├── dialogs.py               (605)   结果卡 / 单词本窗口 / 识词设置
│   ├── bubble.py                (160)   头顶对话气泡
│   │
│   │  ── 蜘蛛本体（程序化，无贴图无骨骼）──
│   ├── crawler_spider.py       (1039)   蜘蛛几何与步态：两骨 IK、阈值步态、匈牙利分配八腿↔八词
│   ├── spider_painter.py        (576)   唯一画蜘蛛的地方：程序化原皮 + 三套贴图皮肤 + 脚下阴影
│   ├── anim.py                  (232)   交互形变：jump / squash / shake / pop / alert / spin
│   │
│   │  ── 数据与能力层 ──
│   ├── lexicon.py               (505)   词库引擎：ecdict 758,497 条 + 考纲标签（本地 SQLite）
│   ├── wordbook.py              (171)   单词本：艾宾浩斯 1/3/7/14 天复习调度
│   ├── industry.py              (151)   行业词库（307 条，独立 sqlite）
│   ├── ocr_engine.py            (188)   RapidOCR 离线识别 + 多线程封装
│   ├── content.py               (134)   全部台词/帮助文案（PET_NAME「微光」在此）
│   └── settings_store.py        (173)   设置持久化 + 改名数据目录迁移（EightLegsGlow→Lexara）
│
├── test/                                ★ 回归测试：10 套件 276 项，全绿（已进打包门禁）
│   ├── test_spider.py           (320)   几何/步态/命中 59 项
│   ├── test_leg_stretch.py      (128)   腿长按需拉伸 15 项
│   ├── test_aim_hold.py         (393)   瞄准保持/腿长上限/配色移植 32 项
│   ├── test_fold.py             (455)   折叠形态（含「收腿后一个像素都不能有」）30 项
│   ├── test_click_through.py    (302)   全窗口命中判定 44 项
│   ├── test_spin.py             (200)   转身动画 13 项
│   ├── test_skin.py             (241)   皮肤系统：换皮不改几何的指纹对拍 25 项
│   ├── test_industry.py         (216)   行业词库 52 项
│   ├── test_ocr_coords.py        (98)   OCR 坐标换算（DPR 不加倍）6 项
│   └── test_thread_ocr.py        (75)   OCR 线程一致性
│
├── tools/                               开发/体检/打包工具（23 个，均独立可跑）
│   ├── build_exe.bat                    ★ 一键打包：先跑测试门禁，再 PyInstaller
│   ├── launcher_probe.py                启动台全时间线离屏渲染 + 几何断言（部署/收回动画）
│   ├── render_layout.py                 布局几何体检（卡片吃满/罐子在右半边）
│   ├── aim_e2e.py                       八腿踩词端到端：真 OCR + 真渲染逐像素验证
│   ├── aim_trigger_probe.py             瞄准触发率体检 13 项
│   ├── skin_sheet.py                    四皮肤 × 三底色对照图（可读性量化）
│   ├── head_joint_sheet.py              头部关节点绘制顺序新旧对照
│   ├── shape_sheet.py / fold_sheet.py / pose_probe.py / leg_reach_sheet.py
│   │                                    姿态/折叠/腿长对照渲染
│   ├── make_icon.py                     从程序化蜘蛛生成 exe 图标
│   ├── build_industry_db.py             生成行业词库 sqlite
│   └── …（aim_compare / clickthrough_probe / gait_probe / hit_diag 等）
│
├── assets/                       (65M)  只读资源（全部打进 exe）
│   ├── ecdict.sqlite            (65M)   主词库 758,497 条
│   ├── exam-tags.sqlite        (416K)   考纲标签 38,855 次（CET4/6、考研、雅思、托福）
│   ├── industry.sqlite         (108K)   行业词库 307 条
│   ├── skins/                           皮肤贴图：3 套 × 身体+头部 PNG + skin_manifest.json
│   ├── jar_crack_01~03.png              玻璃罐三档裂纹贴图
│   └── icon.ico / icon.png              程序图标（由 make_icon.py 从蜘蛛生成）
│
├── ui-preview/                    (196K) HTML 设计原型（零依赖，浏览器直接看）
│   ├── 启动台.html                      完整交互原型（★ 布局落后真机一版：罐子已搬进面板）
│   ├── 设计原型说明.md (README.md)      原型与真机逐条差异及原因
│   └── make_cracks.py / _verify_*.js    裂纹生成与动画参数核对
│
├── dist/                         (495M) 打包产物
│   ├── Lexara.exe              (156M)   ★ 当前成品（词蛛LEXARA）
│   ├── EightLegsGlow.exe / .prev.exe    改名前版本（回滚用）
│   ├── launcher_probe/ aim/ pose/ skin/ shape/   各探针渲染图输出
│   └── backup_before_liquidglass/       Liquid Glass 合并前的源码快照
│
├── backup/                        (204K) 历史源码快照（src_20261015_194706）
└── build/                         (325M) PyInstaller 中间产物（可随时删）
```

## 数据落盘（不在项目目录里）

```
%APPDATA%/Lexara/                       运行数据（改名后）
├── wordbook.json                       单词本（复习队列）
├── settings.json                       启动台/桌宠设置（含皮肤）
└── run.log / run.prev.log              运行日志
%APPDATA%/EightLegsGlow/                旧目录 —— 首次启动自动整体迁移到上面，保留可回滚
```

## 三条架构主线（看代码前先知道）

1. **蜘蛛 = 数据 + 画笔两层**：`crawler_spider.py` 只做几何与步态解算（不画），
   `spider_painter.py` 只画（不解算）。全项目**只有一处**画蜘蛛。
2. **换皮不改形状**：皮肤只替换身体/头部的画法，腿长/命中区/步态逐项与原皮一致，
   `test_skin.py` 用几何指纹对拍钉死。
3. **识词链路**：点蜘蛛头 → `capture` 框选 → `ocr_engine` 本地识别 →
   `lexicon` 查词 → `aim_overlay` 八腿踩词 → 结果卡 → `wordbook` 入复习队列，
   全程无一处联网。
