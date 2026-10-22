// LEXARA 启动台 · QML 版
// 布局规格（用户 2026-10-17 拍板）：
//   左侧 232px 侧栏：Logo / 今日复习 / 收藏夹+背单词 / 底部 换皮肤+设置
//   右侧主区：蜘蛛桌宠大卡片（主视觉）→ 学习活动热力图（日/周/月/年）→
//             底部双容器：输入操作栏（识别引擎|API|输入框|发送）+ 独立「部署」大按钮
// 业务全部走 bridge（隐藏的旧 LauncherWindow 控制器），这里只做呈现。
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Shapes
import Lexara

ApplicationWindow {
    id: root

    // ---------------------------------------------------------- 主题令牌
    // 颜色/尺寸一个都不硬编码在这里了：全部读 Python 侧 `ThemeStore` 暴露的
    // `theme.v`（一张扁平令牌表，来源是 theme.json）。这里只是**起短名字** ——
    // QML 里写 `root.accent`，外部工具里写 `base.accent`，同一个东西。
    //
    // 为什么能热更新：`theme.v` 是带 notify 的 QVariantMap，文件一变整个换掉并
    // 发一次信号，下面所有绑定都会重算。所以 `theme_tool.py set` 或调参页上
    // 拖一下，窗口里的颜色当场就变，不用重启。
    // 查键表：python tools/theme_tool.py list
    readonly property var tv: (typeof theme !== "undefined" && theme) ? theme.v : ({})

    // 基础色
    readonly property string ink: tv["base.ink"]
    readonly property string text: tv["base.text"]
    readonly property string muted: tv["base.muted"]
    readonly property string line: tv["base.line"]
    readonly property string card: tv["base.card"]
    readonly property string panel: tv["base.panel"]
    readonly property string panelAlt: tv["base.panelAlt"]
    readonly property string hover: tv["base.hover"]
    readonly property string white: tv["base.white"]
    readonly property string accent: tv["base.accent"]
    readonly property string accentSoft: tv["base.accentSoft"]
    readonly property string success: tv["base.success"]
    readonly property string warnColor: tv["base.warn"]
    readonly property string warnSoft: tv["base.warnSoft"]
    readonly property string warnLine: tv["base.warnLine"]
    readonly property string warnChip: tv["base.warnChip"]
    readonly property string dangerColor: tv["base.danger"]
    readonly property string dangerSoft: tv["base.dangerSoft"]
    readonly property string dangerLine: tv["base.dangerLine"]
    readonly property string subtleColor: tv["base.subtle"]
    //: 叠在墨绿上的文字色（标题带 / 窗口按钮）：象牙白 + 低饱和的浅绿灰
    readonly property string onDark: tv["base.onDark"]
    readonly property string onDarkMuted: tv["base.onDarkMuted"]
    readonly property string scrim: tv["base.scrim"]
    readonly property string scrimSoft: tv["base.scrimSoft"]

    // 外壳渐变与圆角（从上往下）
    readonly property string shellTop: tv["shell.top"]
    readonly property string shellUpper: tv["shell.upper"]
    readonly property string shellMid: tv["shell.mid"]
    readonly property string shellLow: tv["shell.low"]
    readonly property string shellBottom: tv["shell.bottom"]
    readonly property real shellStop1: tv["shell.stop1"]
    readonly property real shellStop2: tv["shell.stop2"]
    readonly property real shellStop3: tv["shell.stop3"]
    readonly property real shellStop4: tv["shell.stop4"]
    readonly property int shellRadius: tv["shell.radius"]
    readonly property string heroTop: tv["hero.top"]
    readonly property string heroBottom: tv["hero.bottom"]
    readonly property int heroRadius: tv["hero.radius"]
    readonly property real holeRadiusRatio: tv["stage.holeRadiusRatio"]
    readonly property int holeRadiusMax: tv["stage.holeRadiusMax"]

    // 窗口投影
    readonly property string shadowColor: tv["shadow.color"]
    readonly property real shadowStrength: tv["shadow.strength"]
    readonly property real shadowPower: tv["shadow.power"]
    readonly property real shadowOffsetY: tv["shadow.offsetY"]
    readonly property int shadowRadius: tv["shadow.radius"]

    // 按钮（常态 / 悬停 / 按下 / 禁用）
    readonly property string winFg: tv["btn.winFg"]
    readonly property string winHoverBg: tv["btn.winHoverBg"]
    readonly property string winHoverFg: tv["btn.winHoverFg"]
    readonly property string closeHoverBg: tv["btn.closeHoverBg"]
    readonly property string closeHoverFg: tv["btn.closeHoverFg"]
    readonly property string navHoverBg: tv["btn.navHoverBg"]
    readonly property string pillFg: tv["btn.pillFg"]
    readonly property string pillHoverBg: tv["btn.pillHoverBg"]
    readonly property string pillActiveBg: tv["btn.pillActiveBg"]
    readonly property string pillActiveFg: tv["btn.pillActiveFg"]
    readonly property string pillBorder: tv["btn.pillBorder"]
    readonly property string pillWarnFg: tv["btn.pillWarnFg"]
    readonly property string pillWarnBorder: tv["btn.pillWarnBorder"]
    readonly property string primaryBg: tv["btn.primaryBg"]
    readonly property string primaryHoverBg: tv["btn.primaryHoverBg"]
    readonly property string primaryDisabledBg: tv["btn.primaryDisabledBg"]
    readonly property string primaryFg: tv["btn.primaryFg"]
    readonly property string darkBg: tv["btn.darkBg"]
    readonly property string darkHoverBg: tv["btn.darkHoverBg"]
    readonly property string darkDisabledBg: tv["btn.darkDisabledBg"]
    readonly property string darkFg: tv["btn.darkFg"]
    readonly property string ghostBg: tv["btn.ghostBg"]
    readonly property string ghostHoverBg: tv["btn.ghostHoverBg"]
    readonly property string ghostFg: tv["btn.ghostFg"]
    readonly property string dangerFg: tv["btn.dangerFg"]
    readonly property string dangerBorder: tv["btn.dangerBorder"]
    readonly property string inputBg: tv["btn.inputBg"]
    readonly property string inputBorder: tv["btn.inputBorder"]
    readonly property string sliderFill: tv["btn.sliderFill"]
    readonly property string sliderGroove: tv["btn.sliderGroove"]
    readonly property string sliderHandle: tv["btn.sliderHandle"]
    readonly property string switchOn: tv["btn.switchOn"]
    readonly property string switchOff: tv["btn.switchOff"]
    readonly property string switchKnob: tv["btn.switchKnob"]

    // 学习日志点阵
    readonly property string heatEmpty: tv["heat.empty"]
    readonly property string heatLight: tv["heat.light"]
    readonly property string heatDeep: tv["heat.deep"]

    //: "" | "skins" | "settings" —— 覆盖面板（换装 / 设置）
    property string overlay: ""
    //: 收藏夹是否展开（五个分类 + 未分类）。默认收起，避免首屏被分类占满。
    property bool favOpen: false

    // ------------------------------------------------------ 覆盖面板：可拖 / 可收
    // 用户 2026-10-18：设置 / 换装 / 背单词这些弹层「要能拖、能最小化」。
    //
    // 做法不是开独立窗口：那样会多出任务栏图标，也没法贴在外壳上统一投影。
    // 而是在同一层里让它们变成真·浮动面板：
    //   · 标题栏按住能拖（`DragBar` 组件）
    //   · 「—」把整块收成一条 56px 的标题栏（面板自己的 `collapsed`）
    //   · 一旦拖动或收起就撤掉灰遮罩（`overlayPinned` 转 true）——
    //     否则拖开了还是一层灰挡着、点任何地方都关掉，等于白拖
    //
    // 位置状态存在面板自己的 x/y 上，这里只提供三个动作，避免 6 份重复逻辑。
    property bool overlayPinned: false
    //: 收起后保留的高度：18 上下内边距 + 30 标题行 + 余量
    readonly property int overlayBarHeight: 56

    //: 面板 id ↔ overlay 名字。集中一处，新加面板时只改这张表。
    function overlayPanel(name) {
        if (name === "skins") return skinsPanel
        if (name === "settings") return settingsPanel
        if (name === "api") return apiPanel
        if (name === "export") return exportPanel
        if (name === "chat") return chatPanel
        if (name === "review") return reviewPanel
        if (name === "help") return helpPanel
        return null
    }

    //: 遍历当前可见的覆盖面板。面板自己声明 `isPanel: true` 作标记，
    //: 这样根窗口不用把 6 个 id 各写一遍（漏一个就会在缩放时跑出窗口）。
    function forEachOverlay(fn) {
        if (!overlayLayer)
            return
        var kids = overlayLayer.children
        for (var i = 0; i < kids.length; i++) {
            var child = kids[i]
            if (child && child.isPanel && child.visible)
                fn(child)
        }
    }

    function centerOverlay(panel) {
        if (!panel || !panel.parent)
            return
        panel.x = Math.round((panel.parent.width - panel.width) / 2)
        panel.y = Math.round((panel.parent.height - panel.height) / 2)
    }

    //: 拖到哪里都得留一截在窗口里，否则松手就再也抓不回来了。
    function clampOverlay(panel) {
        if (!panel || !panel.parent)
            return
        var minVisible = 96
        var maxX = panel.parent.width - minVisible
        var maxY = panel.parent.height - 40
        var minX = minVisible - panel.width
        if (panel.x > maxX)
            panel.x = maxX
        if (panel.x < minX)
            panel.x = minX
        if (panel.y > maxY)
            panel.y = maxY
        if (panel.y < 0)
            panel.y = 0
    }

    //: 「—」按钮：收成一条标题栏 / 再展开。收起一定转浮动 —— 收起来了还被
    //: 一层灰罩着、点哪儿都关掉，那就不是「最小化」而是「藏起来」。
    //: 收起时保持左上角不动（像窗口最小化再还原），不重新居中。
    function toggleOverlayCollapsed(panel) {
        if (!panel)
            return
        panel.collapsed = !panel.collapsed
        root.overlayPinned = true
    }

    //: 打开面板 = 回到「居中 + 遮罩」的初始观感，收起状态也不延到下一次。
    onOverlayChanged: {
        root.overlayPinned = false
        var panel = root.overlayPanel(root.overlay)
        if (!panel)
            return
        panel.collapsed = false
        // 等 width/height 的绑定先按新尺寸生效，再居中；否则按旧高度算会偏。
        Qt.callLater(function() { root.centerOverlay(panel) })
    }

    // ---------------------------------------------------------- 展示区「镂空」
    // 展示区不是画一块白板，而是在外壳底色与卡片渐变上**各挖一个洞**：窗口本身
    // 是透明帧（`color: "transparent"` + FramelessWindowHint），所以洞里直接是
    // 桌面。JarView 在那上面盖一层白色 50%（alpha 128）—— 用户要的「中间有点
    // 镂空、能直接看到桌面」就是这个叠加结果。
    //
    // 洞的几何必须和 `JarView.stage_rect()` 对齐：它把整个控件内缩 1px 当作
    // 展示区，所以这里也内缩 1px，否则边上会露出一圈 1px 的卡片渐变。
    //
    // 为什么不用绑定而是 `refreshPortal()`：`jarItem` 在文件后半段才创建，
    // 绑定第一次求值时它是 null（会因为「读不到 null 的属性」刷警告，而且
    // 绑到 id 上不会产生依赖，创建后也不会重算）。改成显式函数 + 几何信号，
    // 布局一落定就重新算一遍。
    property rect portalInShell: Qt.rect(0, 0, 0, 0)
    property rect portalInHero: Qt.rect(0, 0, 0, 0)
    property real portalRadius: 0

    function refreshPortal() {
        if (!jarItem || !hero || !shell)
            return
        var w = Math.max(0, jarItem.width - 2)
        var h = Math.max(0, jarItem.height - 2)
        if (w < 8 || h < 8) {
            // 布局还没算完：先不挖洞，等几何信号再来一次。
            portalInHero = Qt.rect(0, 0, 0, 0)
            portalInShell = Qt.rect(0, 0, 0, 0)
            return
        }
        var a = jarItem.mapToItem(hero, 0, 0)
        var nextHero = Qt.rect(a.x + 1, a.y + 1, w, h)
        var b = jarItem.mapToItem(shell, 0, 0)
        var nextShell = Qt.rect(b.x + 1, b.y + 1, w, h)
        var nextRadius = Math.min(root.holeRadiusMax, h * root.holeRadiusRatio)
        // 值没变就不写回：拖窗口时这个函数会被调用很多次，每写一次都会让
        // Shape 重新生成路径。qml 的 rect 是值类型，可以直接比较。
        if (portalInHero !== nextHero)
            portalInHero = nextHero
        if (portalInShell !== nextShell)
            portalInShell = nextShell
        if (portalRadius !== nextRadius)
            portalRadius = nextRadius
    }

    onWidthChanged: {
        refreshPortal()
        root.relayoutOverlays()
    }
    onHeightChanged: {
        refreshPortal()
        root.relayoutOverlays()
    }

    //: 窗口尺寸变化时：模态态保持居中，浮动态只把面板夹回窗口内（别动用户摆的位置）。
    function relayoutOverlays() {
        if (root.overlayPinned)
            root.forEachOverlay(root.clampOverlay)
        else
            root.forEachOverlay(root.centerOverlay)
    }
    //: 主题里改了洞的圆角比例/上限，也要重算（否则要拖一下窗口才变）
    onTvChanged: refreshPortal()
    Component.onCompleted: {
        //: 没有注入 theme 就等于「所有颜色都是 undefined」，界面会一片黑。
        //: 与其让人对着黑屏猜，不如在日志里说清楚少了什么。
        if (typeof theme === "undefined")
            console.warn("[LEXARA] 缺少 theme 上下文属性（应由 LauncherBridge.run 注入）")
        refreshPortal()
    }

    // 统一的发送入口（输入框回车 / 点发送走同一条路，不会出现两套行为）。
    // bridge.send() 返回 false 表示**请求没有发出去**，此时不清空输入框 ——
    // 用户打的字不该因为一次失败就没了。
    function submitChat() {
        root.submitChatText(aiInput.text)
    }
    function submitChatText(text) {
        if (!bridge.aiReady || bridge.chatBusy)
            return
        var body = (text || "").trim()
        if (!body)
            return
        // bridge.send() 返回 false 说明**请求没发出去**（比如还没配模型），
        // 此时不要把用户辛苦打的字清掉。
        if (bridge.send(body)) {
            aiInput.clear()
            chatInput.clear()
            root.overlay = "chat"
        }
    }
    function useExample(text) {
        aiInput.text = text
        root.submitChat()
    }

    // 消息下方的状态行：pending / done / error 都要说得清楚，
    // 不能用「转圈」假装在工作，也不能错误了还不说为什么。
    function aiStateText(message) {
        if (message.state === "pending")
            return "请求中…"
        if (message.state === "error")
            return (message.error || "请求失败。")
        var parts = []
        if (message.at)
            parts.push(message.at)
        if (message.elapsed)
            parts.push(message.elapsed + "s")
        if (message.model)
            parts.push(message.model)
        return parts.join(" · ")
    }

    // 引擎说明：官方给了 reason 就照抄；没给也不能空着，
    // 要让用户知道「没结论」和「坏了」不是一回事。
    function engineHint(engine) {
        if (engine.reason && engine.reason !== "")
            return engine.reason
        if (engine.state === "unknown")
            return "还没验证过可用性，启动后由识词模块在后台探测。"
        if (engine.state === "loading")
            return "正在加载模型并做一次最小推理验证。"
        if (engine.state === "available")
            return "可用。"
        return "识词模块没给出具体原因。"
    }

    visible: true
    // 窗口比可见卡片大一圈：四周 22px 是透明的投影区（见 shadowMargin）。
    // 1180×760 是**卡片**的尺寸，保持不变，所以窗宽 = 1180 + 2×22。
    width: 1236
    height: 816
    minimumWidth: 1036
    minimumHeight: 716
    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint
    font.family: "Microsoft YaHei UI"
    font.pixelSize: 13

    // ------------------------------------------------------------ 窗口投影
    // 无边框 + 透明窗口在 Windows 上拿不到系统投影（DWM 只为有边框的窗口画），
    // 所以自己画一层：窗口四周留 `shadowMargin` 的透明边距，卡片缩进去，
    // 边距里画一圈由外向内加深的圆角矩形（叠加 alpha 近似高斯衰减）。
    //
    // 为什么不用 `MultiEffect`/`DropShadow`：那两个都是「把源纹理按 item 尺寸
    // 再采样一遍」。源一旦比 item 小就会被**拉伸**（实测卡片被放大了一圈），
    // 源设 `visible:false` 又直接没影子；而窗口中间那个透视洞要求阴影必须
    // 「绕着洞走」，滤镜类方案都处理不了。Canvas 是逐笔画的，可以精确地
    // 只画外圈、再把洞 `destination-out` 擦掉。
    readonly property int shadowMargin: root.visibility === Window.Maximized ? 0 : tv["shadow.margin"]
    readonly property int shadowSteps: tv["shadow.steps"]

    //: 把 "#RRGGBB" / "#AARRGGBB" 拆成 canvas 能用的 rgba()。投影颜色是外部
    //: 可调的，不能像以前那样把 `rgba(12,30,22,...)` 写死在绘制代码里。
    function rgbaOf(hex, alpha) {
        var text = String(hex || "#000000").replace("#", "")
        if (text.length === 3)
            text = text.charAt(0) + text.charAt(0) + text.charAt(1) + text.charAt(1)
                   + text.charAt(2) + text.charAt(2)
        var offset = text.length === 8 ? 2 : 0          // #AARRGGBB 前两位是 alpha
        var r = parseInt(text.substr(offset, 2), 16)
        var g = parseInt(text.substr(offset + 2, 2), 16)
        var b = parseInt(text.substr(offset + 4, 2), 16)
        if (isNaN(r) || isNaN(g) || isNaN(b))
            return "rgba(12, 30, 22, " + alpha + ")"
        return "rgba(" + r + ", " + g + ", " + b + ", " + alpha.toFixed(4) + ")"
    }

    Canvas {
        id: windowShadow
        anchors.fill: parent
        visible: root.shadowMargin > 0
        // 卡片/展示区一变就重画（静态画面，不是逐帧）
        Connections {
            target: root
            function onPortalInShellChanged() { windowShadow.requestPaint() }
            function onWidthChanged() { windowShadow.requestPaint() }
            function onHeightChanged() { windowShadow.requestPaint() }
            //: 主题里改了投影参数（浓度/层数/颜色/下沉）也要立刻重画
            function onTvChanged() { windowShadow.requestPaint() }
        }
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            if (root.shadowMargin <= 0)
                return
            var m = root.shadowMargin
            var x = m, y = m, w = shell.width, h = shell.height
            var steps = Math.max(1, root.shadowSteps)
            var strength = root.shadowStrength
            var power = root.shadowPower
            var sink = root.shadowOffsetY
            // 由外向内叠：越靠近卡片，累计不透明度越高（近似衰减）
            for (var i = steps; i >= 1; i--) {
                var grow = i - 0.5
                var t = i / (steps + 2)
                var a = strength * Math.pow(1 - t, power)
                roundedPath(ctx, x - grow, y - grow + sink * (1 - t),
                            w + grow * 2, h + grow * 2, root.shadowRadius + grow)
                ctx.fillStyle = root.rgbaOf(root.shadowColor, a)
                ctx.fill()
            }
            // 透视区不能被影子盖住：把洞原样擦掉（destination-out）
            var hole = root.portalInShell
            if (hole.width > 1 && hole.height > 1) {
                ctx.globalCompositeOperation = "destination-out"
                roundedPath(ctx, hole.x, hole.y, hole.width, hole.height,
                            root.portalRadius)
                ctx.fillStyle = "#000000"
                ctx.fill()
                ctx.globalCompositeOperation = "source-over"
            }
        }
    }

    // Canvas 里没有现成的圆角矩形 API，用 arcTo 拼一条路径
    function roundedPath(ctx, x, y, w, h, r) {
        var rr = Math.max(0, Math.min(r, Math.min(w, h) / 2))
        ctx.beginPath()
        ctx.moveTo(x + rr, y)
        ctx.lineTo(x + w - rr, y)
        ctx.arcTo(x + w, y, x + w, y + rr, rr)
        ctx.lineTo(x + w, y + h - rr)
        ctx.arcTo(x + w, y + h, x + w - rr, y + h, rr)
        ctx.lineTo(x + rr, y + h)
        ctx.arcTo(x, y + h, x, y + h - rr, rr)
        ctx.lineTo(x, y + rr)
        ctx.arcTo(x, y, x + rr, y, rr)
        ctx.closePath()
    }

    // ------------------------------------------------------------ 外壳卡片
    // 底色不再由 Rectangle 铺（那样没法挖洞），改成子级 Shape：一条路径画
    // 「圆角矩形 + 展示区圆弧洞」（奇偶填充 = 洞是真空的），第二条路径只描边。
    // 洞的位置绑到 `portalInShell`，窗口一缩放就跟着走。
    Rectangle {
        id: shell
        anchors.fill: parent
        anchors.margins: root.shadowMargin
        radius: root.shellRadius
        color: "transparent"
        border.width: 0

        Shape {
            anchors.fill: parent
            // ★ 不要加回 layer/samples：这两处离屏层在 1854x1224@1.5
            //   下要一张 MSAA 4x 的 FBO，实测常驻 +68MB、峰值 +105MB，
            //   而逐像素 diff 与不加 layer 完全一致（Shape 填充自带抗锯齿）。
            ShapePath {
                strokeColor: "transparent"
                fillRule: ShapePath.OddEvenFill
                // 整窗底色：上墨绿 → 下象牙白，从上往下渐变。
                // 深色段只留在顶部（标题带 + Logo 区），到 40% 就完全落到象牙白
                // 上 —— 再往下会压到「背单词 / 收藏夹」的深色文字，中间那段灰绿
                // 最不好读。停靠点是按这个约束压缩过的，不是随手取的。
                // 五个色 + 四个停靠点全部来自主题（shell.*），可外部调。
                fillGradient: LinearGradient {
                    x1: 0
                    y1: 0
                    x2: 0
                    y2: shell.height
                    GradientStop { position: 0.00; color: root.shellTop }
                    GradientStop { position: root.shellStop1; color: root.shellUpper }
                    GradientStop { position: root.shellStop2; color: root.shellMid }
                    GradientStop { position: root.shellStop3; color: root.shellLow }
                    GradientStop { position: root.shellStop4; color: root.shellBottom }
                    GradientStop { position: 1.00; color: root.shellBottom }
                }
                PathRectangle {
                    x: 0
                    y: 0
                    width: shell.width
                    height: shell.height
                    radius: root.shellRadius
                }
                PathRectangle {
                    x: root.portalInShell.x
                    y: root.portalInShell.y
                    width: Math.max(0, root.portalInShell.width)
                    height: Math.max(0, root.portalInShell.height)
                    radius: root.portalRadius
                }
            }
            // 外描边单独一条路径：和填充共用一条会连洞的边也描上，
            // 展示区就多出一道不存在的框线。
            ShapePath {
                fillColor: "transparent"
                strokeColor: root.line
                strokeWidth: 1
                PathRectangle {
                    x: 0.5
                    y: 0.5
                    width: shell.width - 1
                    height: shell.height - 1
                    radius: root.shellRadius
                }
            }
        }

        // ------------------------------------------------------ 顶部拖动带
        MouseArea {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 44
            onPressed: function (mouse) {
                if (mouse.button === Qt.LeftButton)
                    root.startSystemMove()
            }
        }

        // ------------------------------------------------------ 左侧导航栏
        // 侧栏不再有自己的底色：整窗是墨绿→象牙白的渐变，侧栏若再罩一层
        // 半透明米色，顶部会和主区拼出一道生硬的灰绿竖缝。透明之后渐变是
        // 连贯的，压在深色上的文字（Logo 下的说明）单独换成浅色。
        Rectangle {
            id: side
            width: 232
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            color: "transparent"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 8

                // 2.1 Logo：直接压在渐变底色上，不套白卡。
                //     素材（assets/ui/lexara_logo.png）已抠成透明底、并染成象牙白 ——
                //     原图的墨黑字放在 #1D3D31 上等于看不见，所以换成 onDark 同色。
                //     尺寸按素材自身比例（440×119）算，不写死高度，换 logo 不会变形。
                Image {
                    Layout.fillWidth: true
                    Layout.preferredHeight: width * 119 / 440
                    Layout.topMargin: 4
                    source: logoUrl
                    sourceSize.width: 440
                    sourceSize.height: 119
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    mipmap: true
                }

                Label {
                    text: "具身化语言学习"
                    font.pixelSize: 12
                    // 这一行落在墨绿段上，用浅色；再往下的导航项已经在象牙白上，
                    // 保持墨色。同一个侧栏里两种前景色是**因为底色变了**。
                    color: root.onDarkMuted
                    Layout.leftMargin: 2
                }

                Item { Layout.preferredHeight: 6 }

                // ---- 导航区（可滚动）--------------------------------------
                // 收藏夹展开后行数会变多；整块放进 ScrollView，底部
                // 「换皮肤 / 设置」固定在滚动区之外 —— 展开收藏夹永远挤不掉它。
                ScrollView {
                    id: navScroll
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ScrollBar.vertical.policy: ScrollBar.AsNeeded

                    ColumnLayout {
                        width: navScroll.availableWidth
                        spacing: 8

                        // 2.2 今日复习（紧接 Logo，不再留大块空白）
                        Rectangle {
                            Layout.fillWidth: true
                            radius: 12
                            color: root.card
                            border.color: root.line
                            border.width: 1
                            implicitHeight: reviewCol.implicitHeight + 22

                            ColumnLayout {
                                id: reviewCol
                                anchors.fill: parent
                                anchors.margins: 11
                                spacing: 5

                                Label {
                                    text: "今日复习"
                                    font.pixelSize: 13
                                    font.bold: true
                                    color: root.ink
                                }
                                RowLayout {
                                    spacing: 4
                                    Label { text: "剩余"; font.pixelSize: 12; color: root.muted }
                                    Label {
                                        text: bridge.due
                                        font.pixelSize: 15
                                        font.bold: true
                                        color: root.accent
                                    }
                                    Label { text: "未复习"; font.pixelSize: 12; color: root.muted }
                                }
                                RowLayout {
                                    spacing: 4
                                    Label { text: "总共"; font.pixelSize: 12; color: root.muted }
                                    Label {
                                        text: bridge.total
                                        font.pixelSize: 13
                                        font.bold: true
                                        color: root.text
                                    }
                                    Label { text: "词"; font.pixelSize: 12; color: root.muted }
                                }
                            }
                        }

                        // 2.2 「背单词」在「收藏夹」**上方**（用户明确要求）
                        SideAction {
                            iconChar: "▶"
                            label: "背单词"
                            big: true
                            onClicked: { bridge.openReview(); root.overlay = "review" }
                        }

                        // 收藏夹：可展开 / 收起，五个分类 + 未分类兜底
                        SideAction {
                            id: favToggle
                            iconChar: root.favOpen ? "▾" : "▸"
                            label: "收藏夹"
                            big: true
                            onClicked: root.favOpen = !root.favOpen
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.leftMargin: 10
                            spacing: 2
                            visible: root.favOpen

                            Repeater {
                                model: bridge.favorites
                                delegate: Rectangle {
                                    id: favRow
                                    required property var modelData
                                    Layout.fillWidth: true
                                    implicitHeight: 28
                                    radius: 8
                                    color: favHover.containsMouse ? root.navHoverBg : "transparent"

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 10
                                        anchors.rightMargin: 8
                                        spacing: 6
                                        Label {
                                            text: favRow.modelData.label || ""
                                            font.pixelSize: 12
                                            color: root.text
                                            Layout.fillWidth: true
                                        }
                                        Label {
                                            // 收藏单词数 / 该分类词库总词数；
                                            // 串由 bridge 拼好（分母不可用是「3/—」，
                                            // 「未分类」只显示计数），QML 不编数字。
                                            text: favRow.modelData.display
                                                  || (favRow.modelData.count + "/—")
                                            font.pixelSize: 11
                                            color: root.muted
                                        }
                                    }
                                    MouseArea {
                                        id: favHover
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: bridge.openWordbookCategory(
                                                       favRow.modelData.id)
                                    }
                                }
                            }

                            // 导出入口：跟着收藏夹展开出现（导的就是这批词），
                            // 不抢首屏空间。真正的格式选择在对齐的导出面板里。
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: 26
                                radius: 8
                                color: exportHover.containsMouse ? root.navHoverBg
                                                                 : "transparent"
                                Label {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 10
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "导出单词本…"
                                    font.pixelSize: 12
                                    color: root.accent
                                }
                                MouseArea {
                                    id: exportHover
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.overlay = "export"
                                }
                            }
                        }
                    }
                }

                // 2.3 底部：图标 + 文字整体放大约 2 倍（视觉目标），
                //     点击热区 56px 高，不与滚动区抢空间。
                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: root.line
                }
                SideAction {
                    iconSource: skinIconUrl
                    label: "换皮肤"
                    big: true
                    onClicked: root.overlay = "skins"
                }
                SideAction {
                    iconSource: settingsIconUrl
                    label: "设置"
                    big: true
                    onClicked: root.overlay = "settings"
                }
            }
        }

        // ------------------------------------------------------ 右侧主区
        ColumnLayout {
            anchors.left: side.right
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.margins: 18
            spacing: 12

            // 标题行：页面名 + 状态 + 窗口控制（右上角 最小化/最大化/关闭）
            // 这一带压在墨绿上，所以文字是象牙白而不是墨色。
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                Label {
                    text: "桌面学习空间"
                    font.pixelSize: 16
                    font.bold: true
                    color: root.onDark
                }
                Item { Layout.fillWidth: true }
                Label {
                    text: bridge.status
                    textFormat: Text.StyledText
                    font.pixelSize: 12
                    color: root.onDarkMuted
                    visible: text.length > 0
                }
                WinButton {
                    glyph: "\u2014"
                    fg: root.onDarkMuted
                    hoverBg: root.winHoverBg
                    hoverFg: root.onDark
                    onClicked: bridge.minimize()
                }
                WinButton {
                    glyph: "\u25A1"
                    fg: root.onDarkMuted
                    hoverBg: root.winHoverBg
                    hoverFg: root.onDark
                    onClicked: bridge.toggleMaximize()
                }
                WinButton {
                    glyph: "\u2715"
                    fg: root.onDarkMuted
                    hoverBg: root.closeHoverBg
                    hoverFg: root.closeHoverFg
                    onClicked: bridge.quitApp()
                }
            }

            // 3.1 蜘蛛桌宠大卡片（主视觉中心）
            //     背景是一层很淡的暖色渐变：展示区本身是「白色 50%」的圆角矩形，
            //     铺在纯白卡片上会看不见；有一层淡底，半透明才读得出来。
            Rectangle {
                id: hero
                objectName: "heroCard"
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: root.heroRadius
                color: "transparent"
                border.width: 0

                // 卡片尺寸一变，洞跟着重算（见 root.refreshPortal 的注释）
                onWidthChanged: root.refreshPortal()
                onHeightChanged: root.refreshPortal()
                onXChanged: root.refreshPortal()
                onYChanged: root.refreshPortal()

                // 卡片渐变同样要挖洞（外壳已经挖过一层，这一层不挖还是会被
                // 渐变糊住）。渐变放在 ShapePath.fillGradient 上，填充规则
                // 用奇偶，第二个圆角矩形就是「桌面从这里透进来」的窗口。
                Shape {
                    anchors.fill: parent
                    // ★ 不要加回 layer/samples：这两处离屏层在 1854x1224@1.5
                    //   下要一张 MSAA 4x 的 FBO，实测常驻 +68MB、峰值 +105MB，
                    //   而逐像素 diff 与不加 layer 完全一致（Shape 填充自带抗锯齿）。
                    ShapePath {
                        fillRule: ShapePath.OddEvenFill
                        strokeColor: "transparent"
                        fillGradient: LinearGradient {
                            x1: 0
                            y1: 0
                            x2: 0
                            y2: hero.height
                            GradientStop { position: 0.0; color: root.heroTop }
                            GradientStop { position: 1.0; color: root.heroBottom }
                        }
                        PathRectangle {
                            x: 0
                            y: 0
                            width: hero.width
                            height: hero.height
                            radius: root.heroRadius
                        }
                        PathRectangle {
                            x: root.portalInHero.x
                            y: root.portalInHero.y
                            width: Math.max(0, root.portalInHero.width)
                            height: Math.max(0, root.portalInHero.height)
                            radius: root.portalRadius
                        }
                    }
                    ShapePath {
                        fillColor: "transparent"
                        strokeColor: root.line
                        strokeWidth: 1
                        PathRectangle {
                            x: 0.5
                            y: 0.5
                            width: hero.width - 1
                            height: hero.height - 1
                            radius: root.heroRadius
                        }
                    }
                }

                Item {
                    anchors.fill: parent
                    anchors.leftMargin: 14
                    anchors.rightMargin: 14
                    anchors.topMargin: 16
                    anchors.bottomMargin: 54

                    // 展示区 = 半透明白圆角矩形（JarView 画），约 2:1 的横幅比例：
                    // 比 1.75 更宽，蜘蛛的行走区间（0.28w~0.72w）才不会挤在中间，
                    // 卡片左右也不会剩一圈空白渐变。窗口变窄时先压宽度。
                    SpiderJar {
                        id: jarItem
                        objectName: "spiderJar"
                        jar: bridge.jar
                        anchors.centerIn: parent
                        width: Math.min(parent.width, parent.height * 2.0)
                        height: width / 2.0
                        // 展示区一动，挖洞的矩形就要跟着动（否则洞口和底板错位，
                        // 边缘会露出 1px 的卡片底色）
                        onWidthChanged: root.refreshPortal()
                        onHeightChanged: root.refreshPortal()
                        onXChanged: root.refreshPortal()
                        onYChanged: root.refreshPortal()
                    }
                }

                ColumnLayout {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 14
                    spacing: 2
                    Label {
                        Layout.alignment: Qt.AlignHCenter
                        text: "词蛛 LEXARA"
                        font.pixelSize: 15
                        font.bold: true
                        color: root.ink
                    }
                    Label {
                        Layout.alignment: Qt.AlignHCenter
                        text: "在桌面 养一只 陪你背单词的蜘蛛"
                        font.pixelSize: 12
                        color: root.muted
                    }
                }
            }

            // 3.2 学习日志（自然年点阵）
            //     日/周/月/年选择器已删除（任务书 §2.6）。
            //     2026-10-19：窗口从「滚动近一年」改成自然年 —— 1 月到 12 月
            //     从左到右一列列排开，月份标签由 HeatGrid 自己画。
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 208
                radius: 14
                color: root.card
                border.color: root.line
                border.width: 1

                HeatGrid {
                    id: heat
                    anchors.fill: parent
                    anchors.margins: 1
                }

                RowLayout {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.topMargin: 12
                    anchors.leftMargin: 18
                    anchors.rightMargin: 14
                    spacing: 8

                    Label {
                        // 「已打卡 XX 天」= 有学习活动的**去重自然日**数，
                        // 由 bridge.activity 从真实事件表算出（不是打开天数）。
                        text: "学习日志 · 已打卡 "
                              + (bridge.activity.checked || 0) + " 天"
                        font.pixelSize: 13
                        font.bold: true
                        color: root.ink
                    }

                    // 蓝色圆圈指示的位置：日历颜色说明（可关闭 / Esc）
                    Rectangle {
                        id: legendBtn
                        width: 18
                        height: 18
                        radius: 9
                        color: legendHover.containsMouse ? root.accentSoft
                                                         : "transparent"
                        border.color: root.accent
                        border.width: 1
                        Label {
                            anchors.centerIn: parent
                            text: "?"
                            font.pixelSize: 11
                            font.bold: true
                            color: root.accent
                        }
                        MouseArea {
                            id: legendHover
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: legendPopup.opened ? legendPopup.close()
                                                          : legendPopup.open()
                        }
                    }

                    Item { Layout.fillWidth: true }

                    MiniButton {
                        text: "导出图片"
                        onClicked: bridge.exportCalendar()
                    }
                }

                // 颜色说明弹层：模态（挡住底层点击）、点外部或 Esc 关闭、
                // 落在标题右下方，不压住主按钮。
                Popup {
                    id: legendPopup
                    objectName: "legendPopup"
                    x: legendBtn.x + 26
                    y: legendBtn.y + 26
                    width: 336
                    padding: 14
                    modal: true
                    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                    background: Rectangle {
                        radius: 12
                        color: root.card
                        border.color: root.line
                        border.width: 1
                    }
                    contentItem: ColumnLayout {
                        spacing: 8
                        Label {
                            text: "日历颜色怎么读"
                            font.pixelSize: 12
                            font.bold: true
                            color: root.ink
                        }
                        Repeater {
                            // 颜色取自主题（heat.*），所以图例文字不写「浅绿/深绿」——
                            // 把点阵改成别的色系时，标签不会跟着说谎。
                            model: [
                                { c: root.heatLight, t: "浅色",
                                  d: "当天至少完成过一次蜘蛛扫描" },
                                { c: root.heatDeep, t: "深色",
                                  d: "当天有背单词复习或主动问 AI（也扫描过仍是深色）" },
                                { c: root.heatEmpty, t: "灰色", d: "当天没有学习活动" }
                            ]
                            delegate: RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: 8
                                Rectangle {
                                    Layout.alignment: Qt.AlignTop
                                    width: 12; height: 12; radius: 3
                                    color: modelData.c
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: modelData.t + "：" + modelData.d
                                    font.pixelSize: 11
                                    color: root.text
                                    wrapMode: Text.Wrap
                                }
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: "只有真的产生结果才算：扫描要有识别出的词，"
                                  + "背单词要提交自评，AI 要成功发出并收到回复。"
                            font.pixelSize: 10
                            color: root.muted
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }

            // 3.3 底部：输入操作栏 + 帮助 + 独立部署按钮
            // UI 语义必须与真实能力对齐：
            //   · 引擎 pill 显示真实引擎名，点开是真实可用状态（不是装饰）；
            //   · API pill 显示真实配置状态，未配置时给出「去配置」入口；
            //   · 发送按钮在「没配模型 / 正在请求 / 空输入」时**必须禁用**，
            //     不允许出现「能点但发出去的是一句假提示」。
            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 58
                    radius: 14
                    color: root.card
                    border.color: aiInput.activeFocus ? root.accent : root.line
                    border.width: 1

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 8

                        // 首位是**模型**入口（任务书 §2.7）：真实模型名来自
                        // bridge.aiSnapshot，没配置时明确写「未配置模型」。
                        // 识别引擎已移进设置面板，这里不再占位。
                        PillButton {
                            text: bridge.aiReady
                                  ? ("模型 · " + (bridge.aiSnapshot.model || "已配置"))
                                  : "未配置模型"
                            checked: root.overlay === "api"
                            tone: bridge.aiReady ? "normal" : "warning"
                            onClicked: root.overlay = "api"
                            ToolTip.visible: hovered
                            ToolTip.text: bridge.aiReady
                                          ? ("当前模型：" + bridge.aiSnapshot.model
                                             + "　点此修改")
                                          : "还没有配置模型，点此填写 Base URL / 模型名 / Key"
                            ToolTip.delay: 400
                        }

                        TextField {
                            id: aiInput
                            Layout.fillWidth: true
                            placeholderText: bridge.aiReady
                                             ? "问点什么吧：解释这个单词、用它造三个句子…"
                                             : "配置模型后即可在这里提问（离线识词不受影响）"
                            font.pixelSize: 12
                            color: root.text
                            background: null
                            verticalAlignment: TextInput.AlignVCenter
                            enabled: bridge.aiReady
                            onAccepted: root.submitChat()
                        }
                        // 聊天记录：有消息就计数，点了进入完整对话
                        PillButton {
                            visible: bridge.chatMessages.length > 0
                            text: "对话 " + bridge.chatMessages.length
                            checked: root.overlay === "chat"
                            onClicked: root.overlay = "chat"
                        }
                        // 发送
                        Button {
                            id: sendBtn
                            text: bridge.chatBusy ? "发送中" : "发送"
                            enabled: bridge.aiReady && !bridge.chatBusy
                                     && aiInput.text.trim().length > 0
                            Layout.preferredWidth: 72
                            Layout.preferredHeight: 36
                            onClicked: root.submitChat()
                            ToolTip.visible: hovered && !enabled
                            ToolTip.text: bridge.aiReady
                                          ? "先输入内容"
                                          : "需要先配置 Base URL、模型名和 API Key"
                            ToolTip.delay: 300
                            background: Rectangle {
                                radius: 18
                                color: !sendBtn.enabled ? root.darkDisabledBg
                                       : sendBtn.hovered ? root.darkHoverBg : root.darkBg
                            }
                            contentItem: Label {
                                text: sendBtn.text
                                color: root.darkFg
                                font.pixelSize: 12
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                }

                // 右下角帮助入口：小巧、描边不打底色，不与「部署」抢主视觉，
                // 也不压在窗口缩放热区或输入栏上。
                Button {
                    id: helpBtn
                    Layout.preferredWidth: 40
                    Layout.preferredHeight: 58
                    ToolTip.visible: hovered
                    ToolTip.text: "产品使用教学"
                    ToolTip.delay: 400
                    onClicked: root.overlay = "help"
                    background: Rectangle {
                        radius: 14
                        color: helpBtn.hovered ? root.hover : root.card
                        border.color: root.line
                        border.width: 1
                    }
                    contentItem: Label {
                        text: "?"
                        font.pixelSize: 17
                        font.bold: true
                        color: root.overlay === "help" ? root.accent : root.muted
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                // 独立「部署」大按钮（不入输入栏、不与发送合并）
                // 文字放大约 2 倍并加粗（15 → 26），按钮随之加宽到 176，
                // 高度与输入栏一致，不挤压输入框。
                Button {
                    id: deployBtn
                    text: bridge.deployText
                    enabled: bridge.deployEnabled
                    Layout.preferredWidth: 176
                    Layout.preferredHeight: 58
                    onClicked: bridge.deployOrRecall()
                    background: Rectangle {
                        radius: 14
                        color: !deployBtn.enabled ? root.primaryDisabledBg
                               : deployBtn.hovered ? root.primaryHoverBg : root.primaryBg
                    }
                    contentItem: Label {
                        text: deployBtn.text
                        color: root.primaryFg
                        font.pixelSize: 26
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }

            // 诚实的状态提示（AI 输入未接真实后端）
            Label {
                text: bridge.notice
                visible: bridge.notice !== ""
                font.pixelSize: 11
                color: root.warnColor
                Layout.alignment: Qt.AlignHCenter
            }
        }

        // ------------------------------------------------ 覆盖面板（换装 / 设置）
        // 这两个面板替代旧的 QWidget SettingsSheet：视觉跟主界面同一套 token，
        // 但写回仍然走 bridge → 旧 LauncherWindow → settings.json 同一条路径。
        Item {
            id: overlayLayer
            anchors.fill: parent
            visible: root.overlay !== ""
            z: 100

            Rectangle {
                anchors.fill: parent
                color: root.scrimSoft
                // 浮动态撤掉遮罩：面板被拖到一边之后，后面的启动台要能点。
                visible: !root.overlayPinned
                MouseArea {
                    anchors.fill: parent
                    enabled: !root.overlayPinned
                    onClicked: root.overlay = ""
                }
            }

            Shortcut {
                sequence: "Esc"
                enabled: root.overlay !== ""
                onActivated: root.overlay = ""
            }

            // ---- 换装
            Rectangle {
                id: skinsPanel
                objectName: "skinsPanel"
                visible: root.overlay === "skins"
                width: 560
                //: 收起 = 只剩标题行。内容靠 clip 裁掉，标题行在 ColumnLayout 最前面，
                //: 所以它一定还在原位（这也是不把标题行单独拆出来的原因）。
                height: skinsPanel.collapsed ? root.overlayBarHeight : 404
                clip: true
                radius: 16
                color: root.card
                border.color: root.overlayPinned ? root.accent : root.line
                border.width: 1

                //: 标记 / 收起状态。根窗口靠 isPanel 统一做居中与夹取，不用逐个点名。
                property bool isPanel: true
                property bool collapsed: false

                //: 浮动态遮罩已撤，面板下方就是启动台 —— 空白处也得接住点击，
                //: 否则点一下面板内边距就点到后面的侧栏按钮了。
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.AllButtons
                    onWheel: function(wheel) { wheel.accepted = true }
                }
                //: 标题栏拖动条（与下面的 ColumnLayout 平级，见 DragBar 注释）
                DragBar {
                    panel: skinsPanel
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 6
                    height: 38
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 12

                    RowLayout {
                        spacing: 9
                        Image {
                            source: skinIconUrl
                            sourceSize.width: 22
                            sourceSize.height: 22
                        }
                        Label {
                            text: "换装"
                            font.pixelSize: 15
                            font.bold: true
                            color: root.ink
                        }
                        Item { Layout.fillWidth: true }
                        Label {
                            text: "点一下即刻生效，已部署的桌宠会同步"
                            font.pixelSize: 11
                            color: root.muted
                        }
                        WinButton {
                            glyph: skinsPanel.collapsed ? "\u25A1" : "\u2014"
                            onClicked: root.toggleOverlayCollapsed(skinsPanel)
                        }
                        WinButton {
                            glyph: "\u2715"
                            onClicked: root.overlay = ""
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        columns: 2
                        rowSpacing: 10
                        columnSpacing: 10

                        Repeater {
                            model: bridge.skins
                            delegate: Rectangle {
                                id: skinCard
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                radius: 12
                                color: bridge.currentSkin === modelData.id
                                       ? root.accentSoft : root.panelAlt
                                border.width: bridge.currentSkin === modelData.id ? 2 : 1
                                border.color: bridge.currentSkin === modelData.id
                                              ? root.accent : root.line

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    spacing: 2
                                    Image {
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        source: modelData.thumb
                                        fillMode: Image.PreserveAspectFit
                                        smooth: true
                                        // 96 会把 170px 的缩略图再压一半，腿的 1.25px
                                        // 细线直接被抹掉；132 既能省内存又不糊腿。
                                        sourceSize.width: 132
                                        sourceSize.height: 132
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: modelData.name
                                        horizontalAlignment: Text.AlignHCenter
                                        font.pixelSize: 12
                                        color: bridge.currentSkin === modelData.id
                                               ? root.accent : root.text
                                    }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: bridge.setSkin(modelData.id)
                                }
                            }
                        }
                    }
                }
            }

            // ---- 设置
            // 2026-10-18 重写（任务书 §2.7 / §3）：
            //   · 识别引擎从输入栏移到这里（含每个引擎的真实状态与不可用原因）；
            //   · 整块内容放进 ScrollView —— 加了引擎设置和两个启动开关之后，
            //     固定高度一定会溢出，靠缩字体掩盖问题是自欺；
            //   · 长文本用 wrapMode 换行，长模型名 elide + tooltip；
            //   · 面板高度跟着窗口走（Math.min），窄/矮窗口下按钮不会被裁掉。
            Rectangle {
                id: settingsPanel
                objectName: "settingsPanel"
                visible: root.overlay === "settings"
                width: Math.min(600, Math.max(360, root.width - 80))
                height: settingsPanel.collapsed
                        ? root.overlayBarHeight
                        : Math.min(640, Math.max(320, root.height - 60))
                clip: true
                radius: 16
                color: root.card
                border.color: root.overlayPinned ? root.accent : root.line
                border.width: 1

                //: 标记 / 收起状态（见 skinsPanel 的注释）
                property bool isPanel: true
                property bool collapsed: false

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.AllButtons
                    onWheel: function(wheel) { wheel.accepted = true }
                }
                DragBar {
                    panel: settingsPanel
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 6
                    height: 38
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 9
                        Image {
                            source: settingsIconUrl
                            sourceSize.width: 22
                            sourceSize.height: 22
                        }
                        Label {
                            text: "设置"
                            font.pixelSize: 15
                            font.bold: true
                            color: root.ink
                        }
                        Item { Layout.fillWidth: true }
                        Label {
                            text: "改完即时写入 settings.json"
                            font.pixelSize: 11
                            color: root.muted
                            elide: Text.ElideRight
                            Layout.maximumWidth: 220
                        }
                        WinButton {
                            glyph: settingsPanel.collapsed ? "\u25A1" : "\u2014"
                            onClicked: root.toggleOverlayCollapsed(settingsPanel)
                        }
                        WinButton {
                            glyph: "\u2715"
                            onClicked: root.overlay = ""
                        }
                    }

                    ScrollView {
                        id: settingsScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                        ScrollBar.vertical.policy: ScrollBar.AsNeeded

                        ColumnLayout {
                            width: settingsScroll.availableWidth
                            spacing: 9

                            // ---------------- 识别引擎（原输入栏入口）----------
                            // ★ 只有够两档才画这块：现在只随包发 RapidOCR 一个，
                            //   PaddleOCR 已从引擎清单里删掉。只剩一张「可选但没得选」
                            //   的卡片时，整段都是噪音，直接不占纵向空间。
                            Label {
                                visible: bridge.engines.length > 1
                                text: "识别引擎"
                                font.pixelSize: 12
                                font.bold: true
                                color: root.ink
                            }
                            ColumnLayout {
                                visible: bridge.engines.length > 1
                                Layout.fillWidth: true
                                spacing: 4

                                Repeater {
                                    model: bridge.engines
                                    delegate: Rectangle {
                                        id: engineCard
                                        required property var modelData
                                        readonly property bool usable:
                                            modelData.state === "available"
                                        readonly property bool chosen:
                                            modelData.id === bridge.currentEngine
                                        Layout.fillWidth: true
                                        implicitHeight: engineCol.implicitHeight + 16
                                        radius: 10
                                        color: chosen ? root.accentSoft : root.panelAlt
                                        border.width: 1
                                        border.color: chosen ? root.accent : root.line
                                        opacity: engineCard.usable ? 1 : 0.72

                                        ColumnLayout {
                                            id: engineCol
                                            anchors.fill: parent
                                            anchors.margins: 9
                                            spacing: 3
                                            RowLayout {
                                                spacing: 6
                                                Label {
                                                    text: modelData.name
                                                    font.pixelSize: 12
                                                    font.bold: true
                                                    color: root.ink
                                                }
                                                Label {
                                                    text: modelData.stateLabel
                                                    font.pixelSize: 11
                                                    color: engineCard.usable
                                                           ? root.accent : root.muted
                                                }
                                                Item { Layout.fillWidth: true }
                                                Label {
                                                    visible: engineCard.chosen
                                                    text: "当前"
                                                    font.pixelSize: 11
                                                    color: root.accent
                                                }
                                            }
                                            Label {
                                                Layout.fillWidth: true
                                                text: root.engineHint(modelData)
                                                font.pixelSize: 11
                                                color: root.muted
                                                wrapMode: Text.Wrap
                                            }
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            enabled: engineCard.usable
                                                     && !engineCard.chosen
                                            cursorShape: enabled ? Qt.PointingHandCursor
                                                                 : Qt.ArrowCursor
                                            onClicked: bridge.selectEngine(
                                                           engineCard.modelData.id)
                                        }
                                    }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: "只有真正验证过「可用」的引擎才能切换；"
                                          + "不可用的会写清原因，不会假装能用。"
                                    font.pixelSize: 10
                                    color: root.muted
                                    wrapMode: Text.Wrap
                                }
                            }

                            Rectangle {
                                visible: bridge.engines.length > 1
                                Layout.fillWidth: true; height: 1; color: root.line
                            }

                            // ---------------- AI 模型 --------------------------
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Label {
                                    text: "AI 模型"
                                    font.pixelSize: 12
                                    color: root.text
                                    Layout.preferredWidth: 78
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: bridge.aiReady
                                          ? (bridge.aiSnapshot.model + " · "
                                             + bridge.aiSnapshot.endpoint)
                                          : "未配置（离线识词不受影响）"
                                    font.pixelSize: 11
                                    color: bridge.aiReady ? root.text : root.muted
                                    elide: Text.ElideMiddle
                                    ToolTip.visible: modelHover.containsMouse
                                    ToolTip.text: bridge.aiReady
                                                  ? (bridge.aiSnapshot.model + "　"
                                                     + bridge.aiSnapshot.endpoint)
                                                  : "还没有配置模型"
                                    ToolTip.delay: 350
                                    MouseArea {
                                        id: modelHover
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        onClicked: root.overlay = "api"
                                    }
                                }
                                Button {
                                    text: "去配置"
                                    implicitHeight: 26
                                    onClicked: root.overlay = "api"
                                    background: Rectangle {
                                        radius: 8
                                        color: parent.hovered ? root.accentSoft
                                                              : "transparent"
                                        border.color: root.accent
                                        border.width: 1
                                    }
                                    contentItem: Label {
                                        text: "去配置"
                                        font.pixelSize: 11
                                        color: root.accent
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                }
                            }

                            // ---------------- 识词参数 --------------------------
                            // 「最大识词」= 本次最多处理多少个词（不是腿数：八条腿是并行度）。
                            // 2026-10-19：从连续滑杆改成**四档按钮**（8/16/32/48）。
                            // 滑杆能停在 7 / 23 / 37 这种数上，而实际节奏只可能是
                            // 「八条腿一批、一批批往上加」——中间值记不住也没对应效果。
                            // 档位表由桥接从 `settings_store.MAX_WORDS_CHOICES` 透出，
                            // QML 这边仍然不写字面量。
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Label {
                                    text: "最大识词"
                                    font.pixelSize: 12
                                    color: root.text
                                    Layout.preferredWidth: 78
                                }
                                Repeater {
                                    model: bridge.maxWordsChoices
                                    delegate: PillButton {
                                        required property int modelData
                                        text: modelData + " 个"
                                        checked: bridge.maxWords === modelData
                                        onClicked: bridge.setMaxWords(modelData)
                                    }
                                }
                                Item { Layout.fillWidth: true }
                            }
                            ValueSlider {
                                Layout.fillWidth: true
                                label: "最小置信度"
                                from: 50
                                to: 99
                                value: bridge.minConfPct
                                unit: "%"
                                onActivated: function (v) { bridge.setMinConfPct(v) }
                            }
                            ValueSlider {
                                Layout.fillWidth: true
                                label: "桌宠大小"
                                from: 50
                                to: 150
                                stepSize: 5
                                value: bridge.petScalePct
                                unit: "%"
                                onActivated: function (v) { bridge.setPetScalePct(v) }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Label {
                                    text: "窗口置顶"
                                    font.pixelSize: 12
                                    color: root.text
                                    Layout.preferredWidth: 78
                                }
                                MiniSwitch {
                                    checked: bridge.alwaysOnTop
                                    onToggled: function (v) { bridge.setAlwaysOnTop(v) }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: "桌宠始终浮在其他窗口之上"
                                    font.pixelSize: 11
                                    color: root.muted
                                    wrapMode: Text.Wrap
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Label {
                                    text: "释义卡片"
                                    font.pixelSize: 12
                                    color: root.text
                                    Layout.preferredWidth: 78
                                }
                                MiniSwitch {
                                    checked: bridge.showMeaningCard
                                    onToggled: function (v) { bridge.setShowMeaningCard(v) }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: "识别后弹出释义说明"
                                    font.pixelSize: 11
                                    color: root.muted
                                    wrapMode: Text.Wrap
                                }
                            }

                            // ---------------- 界面主题 --------------------------
                            // 预设列表（含「跟随系统」虚拟档）和当前选中都由桥接
                            // 透出，label 也在桥接侧，这里不写死颜色/id/文案；
                            // 点一颗胶囊 = bridge 整套盖写 theme.json，
                            // ThemeStore 发信号，全窗（含罐子、热力图）即时重绘。
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Label {
                                    text: "界面主题"
                                    font.pixelSize: 12
                                    color: root.text
                                    Layout.preferredWidth: 78
                                }
                                Repeater {
                                    model: bridge.themePresets
                                    delegate: PillButton {
                                        required property var modelData
                                        text: modelData.label
                                        checked: bridge.currentThemePreset === modelData.id
                                        onClicked: bridge.setThemePreset(modelData.id)
                                    }
                                }
                                Item { Layout.fillWidth: true }
                            }
                            Label {
                                Layout.fillWidth: true
                                text: "白天是墨绿 · 象牙白，夜晚是蓝黑；「跟随系统」按 Windows "
                                      + "深浅色自动切换（约一分钟内跟上）。只改启动台配色，桌宠皮肤不受影响。"
                                font.pixelSize: 10
                                color: root.muted
                                wrapMode: Text.Wrap
                            }

                            Rectangle { Layout.fillWidth: true; height: 1; color: root.line }

                            // ---------------- 启动行为 --------------------------
                            Label {
                                text: "启动行为"
                                font.pixelSize: 12
                                font.bold: true
                                color: root.ink
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Label {
                                    text: "开机时启动"
                                    font.pixelSize: 12
                                    color: root.text
                                    Layout.preferredWidth: 78
                                }
                                MiniSwitch {
                                    objectName: "autostartSwitch"
                                    checked: bridge.autostartState.enabled === true
                                    enabled: bridge.autostartState.supported === true
                                    onToggled: function (v) { bridge.setAutostart(v) }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: bridge.autostartState.enabled
                                          ? "已加入当前用户启动项（登录 Windows 后自动运行）"
                                          : "未加入启动项，登录后不会自动运行"
                                    font.pixelSize: 11
                                    color: root.muted
                                    wrapMode: Text.Wrap
                                }
                            }
                            Label {
                                Layout.fillWidth: true
                                text: "只写入当前用户的启动文件夹，不需要管理员权限。"
                                      + "关闭方法：把开关关掉，或删除 Startup 里的 Lexara.lnk。"
                                font.pixelSize: 10
                                color: root.muted
                                wrapMode: Text.Wrap
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Label {
                                    text: "默认部署"
                                    font.pixelSize: 12
                                    color: root.text
                                    Layout.preferredWidth: 78
                                }
                                MiniSwitch {
                                    checked: bridge.autoDeployOnStart
                                    onToggled: function (v) {
                                        bridge.setAutoDeployOnStart(v)
                                    }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: "应用启动后自动让蜘蛛进入桌面（与开机启动是两件事）"
                                    font.pixelSize: 11
                                    color: root.muted
                                    wrapMode: Text.Wrap
                                }
                            }

                            Item { Layout.preferredHeight: 6 }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 1
                        color: root.line
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Button {
                            text: "恢复默认"
                            implicitHeight: 34
                            onClicked: bridge.resetSettings()
                            background: Rectangle {
                                radius: 9
                                color: parent.hovered ? root.hover : "transparent"
                                border.color: root.line
                                border.width: 1
                            }
                            contentItem: Label {
                                text: "恢复默认"
                                font.pixelSize: 12
                                color: root.text
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                        Item { Layout.fillWidth: true }
                        Button {
                            text: "完成"
                            implicitWidth: 96
                            implicitHeight: 34
                            onClicked: root.overlay = ""
                            background: Rectangle {
                                radius: 9
                                color: root.accent
                            }
                            contentItem: Label {
                                text: "完成"
                                font.pixelSize: 12
                                color: root.white
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                }
            }
            // ---- 导出单词本
            // 三个出口（txt/csv/json）只是格式选择，命名和落盘位置交给
            // 系统「另存为」对话框；txt 额外给一个「遮住答案」开关，
            // 导出的就是自测卷。
            Rectangle {
                id: exportPanel
                objectName: "exportPanel"
                visible: root.overlay === "export"
                width: 420
                height: exportPanel.collapsed ? root.overlayBarHeight : 336
                clip: true
                radius: 16
                color: root.card
                border.color: root.overlayPinned ? root.accent : root.line
                border.width: 1

                property string fmt: "txt"
                property bool study: false
                //: 标记 / 收起状态（见 skinsPanel 的注释）
                property bool isPanel: true
                property bool collapsed: false

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.AllButtons
                    onWheel: function(wheel) { wheel.accepted = true }
                }
                DragBar {
                    panel: exportPanel
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 6
                    height: 38
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 10

                    RowLayout {
                        spacing: 9
                        Label {
                            text: "导出单词本"
                            font.pixelSize: 15
                            font.bold: true
                            color: root.ink
                        }
                        Item { Layout.fillWidth: true }
                        Label {
                            text: bridge.total + " 个单词"
                            font.pixelSize: 11
                            color: root.muted
                        }
                        WinButton {
                            glyph: exportPanel.collapsed ? "\u25A1" : "\u2014"
                            onClicked: root.toggleOverlayCollapsed(exportPanel)
                        }
                        WinButton {
                            glyph: "\u2715"
                            onClicked: root.overlay = ""
                        }
                    }

                    Label {
                        text: "自己命名、自己选位置。文本适合带走背，表格适合"
                              + "Excel 里整理，备份能原样导回词蛛。"
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        font.pixelSize: 11
                        color: root.muted
                    }

                    RowLayout {
                        spacing: 6
                        Label {
                            text: "格式"
                            font.pixelSize: 12
                            color: root.text
                            Layout.preferredWidth: 78
                        }
                        PillButton {
                            text: "文本 .txt"
                            checked: exportPanel.fmt === "txt"
                            onClicked: exportPanel.fmt = "txt"
                        }
                        PillButton {
                            text: "表格 .csv"
                            checked: exportPanel.fmt === "csv"
                            onClicked: exportPanel.fmt = "csv"
                        }
                        PillButton {
                            text: "备份 .json"
                            checked: exportPanel.fmt === "json"
                            onClicked: exportPanel.fmt = "json"
                        }
                    }

                    RowLayout {
                        visible: exportPanel.fmt === "txt"
                        spacing: 8
                        Label {
                            text: "遮住答案"
                            font.pixelSize: 12
                            color: root.text
                            Layout.preferredWidth: 78
                        }
                        MiniSwitch {
                            checked: exportPanel.study
                            onToggled: function (v) { exportPanel.study = v }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: "只留单词和音标，释义用下划线代替"
                            font.pixelSize: 11
                            color: root.muted
                            wrapMode: Text.Wrap
                        }
                    }

                    Item { Layout.fillHeight: true }

                    RowLayout {
                        Item { Layout.fillWidth: true }
                        Button {
                            text: "导出"
                            implicitWidth: 96
                            implicitHeight: 34
                            enabled: bridge.total > 0
                            onClicked: {
                                var r = bridge.exportWordbook(exportPanel.fmt,
                                                              exportPanel.study)
                                if (r && r.ok) root.overlay = ""
                            }
                            background: Rectangle {
                                radius: 9
                                color: parent.enabled ? root.accent : root.line
                            }
                            contentItem: Label {
                                text: "导出"
                                font.pixelSize: 12
                                color: root.white
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                }
            }

            // ---- AI 模型配置（Base URL / 模型名 / API Key）
            Rectangle {
                id: apiPanel
                objectName: "apiPanel"
                visible: root.overlay === "api"
                width: 560
                height: apiPanel.collapsed ? root.overlayBarHeight : 470
                clip: true
                radius: 16
                color: root.card
                border.color: root.overlayPinned ? root.accent : root.line
                border.width: 1

                property string apiKeyInput: ""
                property bool keyVisible: false
                //: 标记 / 收起状态（见 skinsPanel 的注释）
                property bool isPanel: true
                property bool collapsed: false

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.AllButtons
                    onWheel: function(wheel) { wheel.accepted = true }
                }
                DragBar {
                    panel: apiPanel
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 6
                    height: 38
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 9

                    RowLayout {
                        spacing: 9
                        Label {
                            text: "AI 模型"
                            font.pixelSize: 15
                            font.bold: true
                            color: root.ink
                        }
                        Item { Layout.fillWidth: true }
                        Label {
                            text: bridge.aiSnapshot.keySourceLabel
                            font.pixelSize: 11
                            color: root.muted
                        }
                        WinButton {
                            glyph: apiPanel.collapsed ? "\u25A1" : "\u2014"
                            onClicked: root.toggleOverlayCollapsed(apiPanel)
                        }
                        WinButton { glyph: "\u2715"; onClicked: root.overlay = "" }
                    }

                    Label {
                        text: "任何 OpenAI 兼容接口都能用。本机模型可填 http://localhost；"
                              + "公网地址必须是 https，否则不会保存。"
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        font.pixelSize: 11
                        color: root.muted
                    }

                    Label { text: "Base URL"; font.pixelSize: 12; color: root.text }
                    TextField {
                        id: apiBaseUrl
                        Layout.fillWidth: true
                        placeholderText: "https://api.openai.com/v1"
                        font.pixelSize: 12
                        text: bridge.aiSnapshot.baseUrl
                    }
                    Label {
                        text: bridge.aiSnapshot.baseUrl
                              ? "实际请求：" + bridge.aiSnapshot.endpoint
                              : "填 Base URL（…/v1）或完整地址（…/chat/completions）都行"
                        font.pixelSize: 11
                        color: root.muted
                        elide: Text.ElideMiddle
                        Layout.fillWidth: true
                    }

                    Label { text: "模型名称"; font.pixelSize: 12; color: root.text }
                    TextField {
                        id: apiModel
                        Layout.fillWidth: true
                        placeholderText: "gpt-4.1-mini"
                        font.pixelSize: 12
                        text: bridge.aiSnapshot.model
                    }

                    RowLayout {
                        Label { text: "API Key"; font.pixelSize: 12; color: root.text }
                        Item { Layout.fillWidth: true }
                        Button {
                            text: apiPanel.keyVisible ? "隐藏" : "显示"
                            implicitWidth: 52
                            implicitHeight: 24
                            visible: apiPanel.apiKeyInput !== ""
                            onClicked: apiPanel.keyVisible = !apiPanel.keyVisible
                            background: Rectangle {
                                radius: 7; color: root.card
                                border.color: root.line; border.width: 1
                            }
                            contentItem: Label {
                                text: parent.text; font.pixelSize: 11
                                color: root.muted
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                    TextField {
                        id: apiKey
                        Layout.fillWidth: true
                        placeholderText: bridge.aiSnapshot.hasKey
                                         ? ("已保存 " + bridge.aiSnapshot.keyHint
                                            + "　·　留空则不修改")
                                         : "sk-…（保存后不会再明文显示）"
                        font.pixelSize: 12
                        echoMode: apiPanel.keyVisible ? TextInput.Normal : TextInput.Password
                        text: apiPanel.apiKeyInput
                        onTextChanged: apiPanel.apiKeyInput = text
                    }
                    Label {
                        text: "密钥经 Windows 加密接口存在本机，不会写进 settings.json 或日志。"
                        font.pixelSize: 11
                        color: root.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    RowLayout {
                        spacing: 8
                        Button {
                            text: bridge.chatTesting ? "测试中…" : "测试连接"
                            enabled: !bridge.chatTesting
                            implicitWidth: 92
                            implicitHeight: 32
                            onClicked: bridge.testAiConnection()
                            background: Rectangle {
                                radius: 9; color: root.card
                                border.color: root.line; border.width: 1
                            }
                            contentItem: Label {
                                text: parent.text; font.pixelSize: 12
                                color: root.text
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: bridge.aiSnapshot.lastTest.message || ""
                            font.pixelSize: 11
                            color: bridge.aiSnapshot.lastTest.ok ? root.success : root.warnColor
                            elide: Text.ElideRight
                        }
                        Button {
                            text: "清除密钥"
                            implicitWidth: 84
                            implicitHeight: 32
                            onClicked: {
                                bridge.clearAiKey()
                                apiPanel.apiKeyInput = ""
                                apiKey.clear()
                                root.overlay = ""
                                root.overlay = "api"
                            }
                            background: Rectangle {
                                radius: 9; color: root.card
                                border.color: root.dangerBorder; border.width: 1
                            }
                            contentItem: Label {
                                text: "清除密钥"; font.pixelSize: 12
                                color: root.dangerColor
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                        Button {
                            text: "保存"
                            implicitWidth: 84
                            implicitHeight: 32
                            onClicked: {
                                bridge.saveAiConfig(apiBaseUrl.text, apiModel.text,
                                                    apiPanel.apiKeyInput)
                                apiPanel.apiKeyInput = ""
                                apiPanel.keyVisible = false
                                apiKey.clear()
                            }
                            background: Rectangle { radius: 9; color: root.accent }
                            contentItem: Label {
                                text: "保存"; font.pixelSize: 12
                                color: root.white
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                }
            }

            // ---- AI 对话（真正的消息区，不再是一句假提示）
            Rectangle {
                id: chatPanel
                objectName: "chatPanel"
                visible: root.overlay === "chat"
                width: 720
                height: chatPanel.collapsed ? root.overlayBarHeight : 540
                clip: true
                radius: 16
                color: root.card
                border.color: root.overlayPinned ? root.accent : root.line
                border.width: 1

                //: 标记 / 收起状态（见 skinsPanel 的注释）
                property bool isPanel: true
                property bool collapsed: false

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.AllButtons
                    onWheel: function(wheel) { wheel.accepted = true }
                }
                DragBar {
                    panel: chatPanel
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 6
                    height: 38
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 10

                    RowLayout {
                        spacing: 8
                        Label {
                            text: "词蛛 AI"
                            font.pixelSize: 15
                            font.bold: true
                            color: root.ink
                        }
                        Label {
                            text: bridge.aiReady ? bridge.aiSnapshot.model : "未配置模型"
                            font.pixelSize: 11
                            color: bridge.aiReady ? root.muted : root.warnColor
                        }
                        Item { Layout.fillWidth: true }
                        MiniButton {
                            text: "新会话"
                            onClicked: bridge.newChatSession()
                        }
                        WinButton {
                            glyph: chatPanel.collapsed ? "\u25A1" : "\u2014"
                            onClicked: root.toggleOverlayCollapsed(chatPanel)
                        }
                        WinButton { glyph: "\u2715"; onClicked: root.overlay = "" }
                    }

                    // 未配置：明确 CTA，不允许「看着能发其实没发」
                    Rectangle {
                        visible: !bridge.aiReady
                        Layout.fillWidth: true
                        height: 58
                        radius: 11
                        color: root.warnSoft
                        border.color: root.warnLine
                        border.width: 1
                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 11
                            spacing: 10
                            Label {
                                Layout.fillWidth: true
                                text: "还没有配置模型。填好 Base URL、模型名和 API Key 之后才能对话；"
                                      + "不配置也能正常离线识词、查词和背单词。"
                                font.pixelSize: 11
                                color: root.warnColor
                                wrapMode: Text.Wrap
                            }
                            MiniButton {
                                text: "配置模型"
                                primary: true
                                onClicked: root.overlay = "api"
                            }
                        }
                    }

                    // 消息列表
                    ListView {
                        id: chatView
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 10
                        boundsBehavior: Flickable.StopAtBounds
                        model: bridge.chatMessages
                        onCountChanged: chatView.positionViewAtEnd()

                        Label {
                            anchors.centerIn: parent
                            visible: bridge.chatMessages.length === 0 && bridge.aiReady
                            width: parent.width * 0.72
                            horizontalAlignment: Text.AlignHCenter
                            text: "随便问点什么。比如：\n"
                                  + bridge.chatExamples.join("\n")
                            font.pixelSize: 12
                            color: root.muted
                            wrapMode: Text.Wrap
                        }

                        delegate: RowLayout {
                            required property var modelData
                            width: chatView.width
                            spacing: 8
                            // 用户消息靠右、AI 回复靠左：用一个只在一侧出现的
                            // 弹性占位实现，而不是改 alignment —— RowLayout
                            // 里 layoutMirroring 会连带把文本方向也翻过去。
                            Item {
                                Layout.fillWidth: true
                                visible: modelData.role === "user"
                            }
                            Rectangle {
                                Layout.maximumWidth: chatView.width * 0.80
                                Layout.preferredWidth: msgBody.implicitWidth + 22
                                radius: 12
                                color: modelData.role === "user"
                                       ? root.accentSoft : root.panel
                                border.width: modelData.role === "user" ? 0 : 1
                                border.color: root.line
                                Layout.preferredHeight: msgBody.implicitHeight + 22

                                ColumnLayout {
                                    id: msgBody
                                    anchors.fill: parent
                                    anchors.margins: 11
                                    spacing: 5
                                    // 纯文本显示：模型输出是不可信输入，
                                    // 这里刻意不做 Markdown/富文本渲染。
                                    TextEdit {
                                        Layout.fillWidth: true
                                        text: modelData.text
                                        font.pixelSize: 13
                                        color: root.text
                                        wrapMode: Text.Wrap
                                        readOnly: true
                                        selectByMouse: true
                                        textFormat: TextEdit.PlainText
                                    }
                                    RowLayout {
                                        spacing: 6
                                        Label {
                                            text: modelData.role === "assistant"
                                                  ? aiStateText(modelData)
                                                  : (modelData.at || "")
                                            font.pixelSize: 11
                                            color: modelData.state === "error"
                                                   ? root.dangerColor : root.subtleColor
                                        }
                                        Item { Layout.fillWidth: true }
                                        MiniButton {
                                            visible: modelData.text !== ""
                                            text: "复制"
                                            onClicked: bridge.copyText(modelData.text)
                                        }
                                        MiniButton {
                                            visible: modelData.state === "error"
                                            text: "重试"
                                            onClicked: root.submitChat()
                                        }
                                    }
                                }
                            }
                        }
                    }

                    RowLayout {
                        spacing: 8
                        TextArea {
                            id: chatInput
                            Layout.fillWidth: true
                            Layout.preferredHeight: 62
                            placeholderText: bridge.aiReady
                                             ? "Enter 发送，Shift+Enter 换行"
                                             : "先配置模型才能发送"
                            font.pixelSize: 13
                            enabled: bridge.aiReady
                            wrapMode: TextArea.Wrap
                            selectByMouse: true
                            background: Rectangle {
                                radius: 10
                                color: root.panel
                                border.color: chatInput.activeFocus ? root.accent : root.line
                                border.width: 1
                            }
                            Keys.onPressed: function (event) {
                                if ((event.key === Qt.Key_Return
                                     || event.key === Qt.Key_Enter)
                                    && !(event.modifiers & Qt.ShiftModifier)) {
                                    event.accepted = true
                                    root.submitChatText(chatInput.text)
                                }
                            }
                        }
                        ColumnLayout {
                            spacing: 6
                            Button {
                                text: bridge.chatBusy ? "停止" : "发送"
                                enabled: bridge.chatBusy
                                         || (bridge.aiReady
                                             && chatInput.text.trim().length > 0)
                                implicitWidth: 78
                                implicitHeight: 32
                                onClicked: bridge.chatBusy ? bridge.cancelChat()
                                           : root.submitChatText(chatInput.text)
                                background: Rectangle {
                                    radius: 9
                                    color: !parent.enabled ? root.darkDisabledBg : root.darkBg
                                }
                                contentItem: Label {
                                    text: parent.text; font.pixelSize: 12
                                    color: root.white
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                            Label {
                                visible: bridge.chatBusy
                                text: "请求中…"
                                font.pixelSize: 11
                                color: root.muted
                            }
                        }
                    }
                }
            }

            // ---- 背单词（复习面板）
            Rectangle {
                id: reviewPanel
                objectName: "reviewPanel"
                visible: root.overlay === "review"
                width: 640
                height: reviewPanel.collapsed ? root.overlayBarHeight : 470
                clip: true
                radius: 16
                color: root.card
                border.color: root.overlayPinned ? root.accent : root.line
                border.width: 1
                // 收起时别再吃空格/回车 —— 卡片被裁掉了，快捷键却还在翻页
                //: 默写弹层开着时**必须让出焦点**：面板 `focus: true` 会触发
                //: `clearFocusInScope`，把弹层里输入框的焦点一起清掉（绑定每
                //: 重算一次就清一次），用户看着光标在闪却打不进字。
                focus: visible && !reviewPanel.collapsed
                       && bridge.reviewStage === "card"
                       && bridge.reviewSpell.open !== true
                Keys.onSpacePressed: {
                    if (!bridge.reviewCard.revealed)
                        bridge.reviewReveal()
                }
                Keys.onReturnPressed: {
                    //: 默写弹层开着时回车归弹层（见 spellInput.onAccepted）。
                    //: **这行必须留着**：Qt 的 Return 键在 TextField 上既发
                    //: `accepted()` 又继续往祖先冒泡，一次回车会同时判「记住了」
                    //: 并把卡片翻走 —— 弹层被 `_reset_spell()` 清掉，用户看到的
                    //: 是「按回车就退出」，实际还悄悄写进了一次假的满分自评。
                    if (bridge.reviewSpell.open === true)
                        return
                    if (bridge.reviewCard.revealed)
                        bridge.reviewGrade(true)
                }

                //: 标记 / 收起状态（见 skinsPanel 的注释）
                property bool isPanel: true
                property bool collapsed: false

                //: AI 辅助（造句 / 同义词）的状态，唯一来源是 Python 侧
                //: `study_help.StudyHelpService.state`。QML **不算任何业务**：
                //: 「能不能点」「显示什么」全看这里的 state。
                readonly property var help: bridge.reviewHelp
                readonly property string helpState: help.state || "idle"
                readonly property bool helpLoading: helpState === "loading"

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.AllButtons
                    onWheel: function(wheel) { wheel.accepted = true }
                }
                DragBar {
                    panel: reviewPanel
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 6
                    height: 38
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 12

                    RowLayout {
                        Label {
                            text: "背单词"
                            font.pixelSize: 15
                            font.bold: true
                            color: root.ink
                        }
                        Item { Layout.fillWidth: true }
                        Label {
                            visible: bridge.reviewStage === "card"
                            text: (bridge.reviewCard.index || 0) + " / "
                                  + (bridge.reviewCard.total || 0)
                            font.pixelSize: 12
                            color: root.muted
                        }
                        WinButton {
                            glyph: reviewPanel.collapsed ? "\u25A1" : "\u2014"
                            onClicked: root.toggleOverlayCollapsed(reviewPanel)
                        }
                        WinButton { glyph: "\u2715"; onClicked: root.overlay = "" }
                    }

                    // ---- 入口页
                    ColumnLayout {
                        visible: bridge.reviewStage === "home"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 14

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            ReviewStat {
                                Layout.fillWidth: true
                                value: bridge.reviewOverview.due
                                label: "今天待复习"
                                highlight: bridge.reviewOverview.due > 0
                            }
                            ReviewStat {
                                Layout.fillWidth: true
                                value: bridge.reviewOverview.reviewedToday
                                label: "今日已复习"
                            }
                            ReviewStat {
                                Layout.fillWidth: true
                                value: bridge.reviewOverview.total
                                label: "单词总数"
                            }
                        }

                        // 分类胶囊：「全部」是虚拟档，其余六行和侧栏收藏夹同一
                        // 口径（bridge.reviewOverview.categories）。选中只影响
                        // 入口页统计作用域和下一轮的复习队列，不动调度算法。
                        Flow {
                            Layout.fillWidth: true
                            spacing: 6
                            Repeater {
                                model: bridge.reviewOverview.categories
                                delegate: PillButton {
                                    required property var modelData
                                    text: modelData.label + " · " + modelData.count
                                    checked: bridge.reviewCategory === modelData.id
                                    onClicked: bridge.setReviewCategory(modelData.id)
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 12
                            color: bridge.reviewOverview.empty ? root.panelAlt : root.panel
                            border.color: root.line
                            border.width: 1
                            ColumnLayout {
                                anchors.centerIn: parent
                                spacing: 8
                                Label {
                                    Layout.preferredWidth: 420
                                    horizontalAlignment: Text.AlignHCenter
                                    wrapMode: Text.Wrap
                                    text: bridge.reviewOverview.empty
                                          ? (bridge.reviewCategory !== "all"
                                             ? "「" + bridge.reviewOverview.categoryLabel
                                               + "」里还没有收进过单词。换个分类，"
                                               + "或先用蜘蛛头框选屏幕上的英文收几个词。"
                                             : "单词本还是空的。先用蜘蛛头框选屏幕上的英文，"
                                               + "把想背的词收进单词本，再回来开始复习。")
                                          : (bridge.reviewOverview.due > 0
                                             ? "有 " + bridge.reviewOverview.due
                                               + " 个词今天该复习了。看到英文先自己想中文，"
                                                 + "想好再点「显示答案」。"
                                             : "今天的到期的词都已经复习完了。"
                                               + (bridge.reviewOverview.nextDueLabel
                                                  ? "下一批 " + bridge.reviewOverview.nextDueLabel + "到期。"
                                                  : ""))
                                    font.pixelSize: 13
                                    color: root.text
                                }
                                Label {
                                    visible: !bridge.reviewOverview.empty
                                    text: "复习间隔：记住了 → 1 / 3 / 7 / 14 天；没记住 → 明天重来。"
                                    font.pixelSize: 11
                                    color: root.muted
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Item { Layout.fillWidth: true }
                            MiniButton {
                                text: "查单词本"
                                visible: !bridge.reviewOverview.empty
                                onClicked: bridge.openWordbook()
                            }
                            MiniButton {
                                text: bridge.reviewOverview.due > 0
                                      ? "只练到期" : "浏览全部"
                                enabled: bridge.reviewOverview.total > 0
                                onClicked: bridge.startReviewSession(
                                               bridge.reviewOverview.due > 0)
                            }
                            MiniButton {
                                text: "开始复习"
                                primary: true
                                enabled: bridge.reviewOverview.total > 0
                                onClicked: bridge.startReviewSession(false)
                            }
                        }
                    }

                    // ---- 卡片页（先回忆 → 再揭示 → 再自评）
                    ColumnLayout {
                        visible: bridge.reviewStage === "card"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 10

                        Rectangle {
                            Layout.fillWidth: true
                            height: 5
                            radius: 3
                            color: root.line
                            Rectangle {
                                width: parent.width * (bridge.reviewCard.progress || 0)
                                height: parent.height
                                radius: 3
                                color: root.accent
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 13
                            color: root.panelAlt
                            border.color: root.line
                            border.width: 1

                            //: 卡片内容整体可滚动。**为什么不是 `anchors.centerIn`**：
                            //: 展开 AI 辅助之后内容会超过卡片高度，居中摆放会把
                            //: 首尾两头同时顶出边框（边框没 clip，看起来像溢出到
                            //: 标题栏上）。用 Flickable + 「内容比视口矮就垂直居中」
                            //: 的 y，既保持原来的观感，又不会真的丢内容。
                            Flickable {
                                id: cardScroll
                                anchors.fill: parent
                                anchors.margins: 18
                                clip: true
                                //: 默写弹窗打开时**整块卡片内容直接不画**。
                                //: 只靠半透明遮罩不够：音标（phonetic）几乎等于答案，
                                //: 30px 的白字在 70% 黑底下还能看出轮廓。隐藏掉最干净，
                                //: 而且遮罩本身还在，层次不会塌。
                                visible: bridge.reviewSpell.open !== true
                                contentWidth: width
                                contentHeight: Math.max(height, cardCol.implicitHeight)
                                boundsBehavior: Flickable.StopAtBounds
                                flickableDirection: Flickable.VerticalFlick
                                interactive: contentHeight > height + 1

                                ColumnLayout {
                                    id: cardCol
                                    width: cardScroll.width
                                    //: 内容比视口矮时保持原来的「垂直居中」观感；
                                    //: 高了就从顶部排起，交给 Flickable 滚。
                                    y: Math.max(0, (cardScroll.height - cardCol.implicitHeight) / 2)
                                    spacing: 9
                                    Label {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: bridge.reviewCard.word || ""
                                        font.pixelSize: 30
                                        font.bold: true
                                        color: root.ink
                                    }
                                    Label {
                                        visible: (bridge.reviewCard.phonetic || "") !== ""
                                        Layout.alignment: Qt.AlignHCenter
                                        // 没有卡片时 bridge.reviewCard 是 {}，
                                        // 直接取字段会拿到 undefined（QML 报警告），
                                        // 所以所有文本字段都走 || "" 兜底。
                                        text: bridge.reviewCard.phonetic || ""
                                        font.pixelSize: 13
                                        color: root.muted
                                    }
                                    RowLayout {
                                        visible: (bridge.reviewCard.level || "") !== ""
                                        Layout.alignment: Qt.AlignHCenter
                                        spacing: 5
                                        Label {
                                            text: bridge.reviewCard.level || ""
                                            font.pixelSize: 11
                                            color: root.accent
                                        }
                                        Label {
                                            text: bridge.reviewCard.stageLabel || ""
                                            font.pixelSize: 11
                                            color: root.muted
                                        }
                                    }
                                    Rectangle {
                                        Layout.alignment: Qt.AlignHCenter
                                        visible: bridge.reviewCard.revealed === true
                                        width: answerCol.implicitWidth + 28
                                        height: answerCol.implicitHeight + 20
                                        radius: 10
                                        color: root.accentSoft
                                        ColumnLayout {
                                            id: answerCol
                                            anchors.centerIn: parent
                                            spacing: 4
                                            Label {
                                                Layout.alignment: Qt.AlignHCenter
                                                Layout.preferredWidth: 460
                                                horizontalAlignment: Text.AlignHCenter
                                                wrapMode: Text.Wrap
                                                text: bridge.reviewCard.meaning || ""
                                                font.pixelSize: 14
                                                color: root.ink
                                            }
                                        }
                                    }
                                    Label {
                                        Layout.alignment: Qt.AlignHCenter
                                        visible: bridge.reviewCard.revealed !== true
                                        text: "先在心里想一下中文意思，然后按空格或点下面的按钮"
                                        font.pixelSize: 12
                                        color: root.muted
                                    }

                                    // ------------------------------------------------ AI 辅助
                                    //: **只在答案揭示之后才出现**。没看到释义就让它造句，
                                    //: 等于跳过「先自己回忆」这一步，卡片就退化成一本例句书了。
                                    RowLayout {
                                        Layout.alignment: Qt.AlignHCenter
                                        Layout.topMargin: 2
                                        visible: bridge.reviewCard.revealed === true
                                        spacing: 8
                                        MiniButton {
                                            text: reviewPanel.helpLoading
                                                  && bridge.reviewHelp.mode === "sentence"
                                                  ? "造句中…" : "造句"
                                            enabled: !reviewPanel.helpLoading
                                            onClicked: bridge.reviewHelpRequest("sentence")
                                        }
                                        MiniButton {
                                            text: reviewPanel.helpLoading
                                                  && bridge.reviewHelp.mode === "synonym"
                                                  ? "同义词中…" : "同义词"
                                            enabled: !reviewPanel.helpLoading
                                            onClicked: bridge.reviewHelpRequest("synonym")
                                        }
                                        //: 默写是**本地判分**，不走 AI、不需要配置模型，
                                        //: 所以它不看 `helpLoading` / `aiReady`。
                                        MiniButton {
                                            text: "默写"
                                            onClicked: bridge.reviewSpellOpen()
                                        }
                                        Label {
                                            visible: !bridge.aiReady
                                            text: "（要先配置模型）"
                                            font.pixelSize: 11
                                            color: root.muted
                                        }
                                    }

                                    //: 结果框：**固定高度 + 内部滚动**。让卡片随回复变高
                                    //: 会把下面的「记住了」按钮推得跳一下，而这块内容本来
                                    //: 就是可选的参考信息，不值得让整个版面跟着抖。
                                    Rectangle {
                                        id: helpBox
                                        Layout.alignment: Qt.AlignHCenter
                                        Layout.fillWidth: true
                                        Layout.maximumWidth: 500
                                        Layout.preferredHeight: 128
                                        visible: reviewPanel.helpState !== "idle"
                                        radius: 10
                                        color: root.panel
                                        border.width: 1
                                        border.color: reviewPanel.helpState === "error"
                                                      ? root.dangerLine : root.line

                                        Label {
                                            id: helpTitle
                                            anchors.left: parent.left
                                            anchors.top: parent.top
                                            anchors.leftMargin: 12
                                            anchors.topMargin: 7
                                            text: {
                                                var h = bridge.reviewHelp
                                                var name = h.modeLabel || "AI 辅助"
                                                if (h.state === "loading")
                                                    return name + " · 生成中…"
                                                if (h.state === "error")
                                                    return name + " · 没成功"
                                                return name + " · AI 生成"
                                            }
                                            font.pixelSize: 11
                                            color: reviewPanel.helpState === "error"
                                                   ? root.dangerColor : root.muted
                                        }

                                        Item {
                                            id: helpClose
                                            anchors.right: parent.right
                                            anchors.top: parent.top
                                            anchors.rightMargin: 10
                                            anchors.topMargin: 4
                                            width: closeLabel.implicitWidth + 10
                                            height: 20
                                            Label {
                                                id: closeLabel
                                                anchors.centerIn: parent
                                                text: "收起"
                                                font.pixelSize: 11
                                                color: root.muted
                                            }
                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                // 收起**只清显示，不清缓存**：再点同一个词是秒回。
                                                onClicked: bridge.reviewHelpClose()
                                            }
                                        }

                                        Flickable {
                                            id: helpFlick
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.top: helpTitle.bottom
                                            anchors.bottom: parent.bottom
                                            anchors.leftMargin: 12
                                            anchors.rightMargin: 12
                                            anchors.topMargin: 4
                                            anchors.bottomMargin: 8
                                            clip: true
                                            contentWidth: width
                                            contentHeight: helpBody.contentHeight
                                            boundsBehavior: Flickable.StopAtBounds
                                            flickableDirection: Flickable.VerticalFlick
                                            interactive: contentHeight > height + 1

                                            //: 只读纯文本：模型输出当不可信输入处理，
                                            //: **不渲染 Markdown**（同对话页的红线）。
                                            //: 可选可复制 —— 用户想把例句抄进笔记是正当需求。
                                            TextEdit {
                                                id: helpBody
                                                width: helpFlick.width
                                                text: {
                                                    var h = bridge.reviewHelp
                                                    if (h.state === "loading")
                                                        return "正在向模型请求，通常 2~5 秒…"
                                                    if (h.state === "error")
                                                        return h.error || "请求失败。"
                                                    return h.text || ""
                                                }
                                                readOnly: true
                                                selectByMouse: true
                                                wrapMode: TextEdit.Wrap
                                                textFormat: TextEdit.PlainText
                                                font.pixelSize: 12
                                                color: reviewPanel.helpState === "error"
                                                       ? root.dangerColor : root.text
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            MiniButton {
                                text: "上一个"
                                enabled: bridge.reviewCard.total > 1
                                onClicked: bridge.reviewStep(-1)
                            }
                            Item { Layout.fillWidth: true }
                            MiniButton {
                                text: "退出复习"
                                onClicked: bridge.reviewExit()
                            }
                            MiniButton {
                                visible: bridge.reviewCard.revealed !== true
                                text: "显示答案（空格）"
                                primary: true
                                onClicked: bridge.reviewReveal()
                            }
                            MiniButton {
                                visible: bridge.reviewCard.revealed === true
                                text: "没记住"
                                danger: true
                                onClicked: bridge.reviewGrade(false)
                            }
                            MiniButton {
                                visible: bridge.reviewCard.revealed === true
                                text: "记住了（回车）"
                                primary: true
                                onClicked: bridge.reviewGrade(true)
                            }
                        }
                    }

                    // ---- 完成页（全部数字来自真实 session）
                    ColumnLayout {
                        visible: bridge.reviewStage === "done"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 14
                        Label {
                            Layout.alignment: Qt.AlignHCenter
                            text: "这一轮练完了"
                            font.pixelSize: 17
                            font.bold: true
                            color: root.ink
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            ReviewStat {
                                Layout.fillWidth: true
                                value: bridge.reviewSummary.answered
                                label: "已练"
                            }
                            ReviewStat {
                                Layout.fillWidth: true
                                value: bridge.reviewSummary.correct
                                label: "记住了"
                                highlight: true
                            }
                            ReviewStat {
                                Layout.fillWidth: true
                                value: bridge.reviewSummary.wrongCount
                                label: "还要再练"
                                highlight: bridge.reviewSummary.wrongCount > 0
                                warn: true
                            }
                            ReviewStat {
                                Layout.fillWidth: true
                                value: bridge.reviewSummary.elapsed + "s"
                                label: "用时"
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 12
                            color: root.panel
                            border.color: root.line
                            border.width: 1
                            Label {
                                anchors.centerIn: parent
                                width: parent.width - 40
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.Wrap
                                text: bridge.reviewSummary.wrongCount > 0
                                      ? "还有 " + bridge.reviewSummary.wrongCount
                                        + " 个词没记住，明天会安排它们再出现一次。"
                                      : "全部记住了。这些词会按 1 / 3 / 7 / 14 天的节奏再来找你。"
                                font.pixelSize: 13
                                color: root.text
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Item { Layout.fillWidth: true }
                            MiniButton {
                                text: "查单词本"
                                onClicked: bridge.openWordbook()
                            }
                            MiniButton {
                                text: bridge.reviewSummary.wrongCount > 0
                                      ? "再练错词" : "再练一轮"
                                enabled: bridge.reviewSummary.wrongCount > 0
                                         || bridge.reviewOverview.total > 0
                                onClicked: bridge.reviewSummary.wrongCount > 0
                                           ? bridge.reviewRetryWrong()
                                           : bridge.startReviewSession(false)
                            }
                            MiniButton {
                                text: "回到首页"
                                primary: true
                                onClicked: bridge.reviewExit()
                            }
                        }
                    }
                }

                // ------------------------------------------------ 默写弹窗
                //: 覆盖整块面板（含底部按钮行），遮罩吃掉所有点击 —— 默写期间
                //: 底下没有任何东西能点，避免「一半在默写、一半在翻卡」。
                //:
                //: **单词不能露**：卡片内容已经由 `cardScroll.visible` 整块隐藏，
                //: 这里再压一层遮罩，是为了不让下面的按钮行和面板底色显得像故障。
                //: 判分在 Python（`spell_check.check`），这里只显示结果。
                Rectangle {
                    id: spellOverlay
                    anchors.fill: parent
                    z: 300
                    visible: bridge.reviewSpell.open === true
                    //: 带一点蓝的深色，而不是纯黑：夜间主题下纯黑遮罩会把
                    //: 雾白文字的余像衬得很脏。
                    color: "#D90B1520"
                    //: **不要给这一层 `focus: visible`**。给过，结果是它把
                    //: `spellInput.forceActiveFocus()` 的焦点抢走（绑定在信号
                    //: 处理器之后才落地），用户根本打不进字，而回车顺着冒泡
                    //: 一路跑到 reviewPanel 上判了「记住了」—— 观感就是
                    //: 「按回车直接退出，还没法默写」。
                    //: Esc 不需要本层有焦点：TextField 不消费 Esc，事件会沿
                    //: 祖先链冒上来，下面的 Keys.onEscapePressed 照样收到。
                    //: 回车**只挂在输入框自己身上**（见 spellInput 的 Keys）。
                    //: 挂在遮罩这一层不管用：TextField 会把 Return 吃掉，事件
                    //: 根本冒不到这里；而在 TextField 上写 `onAccepted` 也不行
                    //: —— 判对后输入框转 `readOnly`，readOnly 不再发 accepted，
                    //: 第二次回车（= 点「完成」）就没反应了。
                    Keys.onEscapePressed: bridge.reviewSpellClose()
                    onVisibleChanged: {
                        if (visible) {
                            spellInput.text = ""
                            spellInput.forceActiveFocus()
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.AllButtons
                        onWheel: function(wheel) { wheel.accepted = true }
                    }

                    Rectangle {
                        anchors.centerIn: parent
                        width: Math.min(420, spellOverlay.width - 64)
                        height: spellCol.implicitHeight + 44
                        radius: 14
                        color: root.panel
                        border.width: 1
                        border.color: root.line

                        ColumnLayout {
                            id: spellCol
                            anchors.fill: parent
                            anchors.margins: 22
                            spacing: 8

                            RowLayout {
                                Layout.fillWidth: true
                                Label {
                                    text: "默写单词"
                                    font.pixelSize: 13
                                    font.bold: true
                                    color: root.ink
                                }
                                Item { Layout.fillWidth: true }
                                Item {
                                    width: spellQuit.implicitWidth + 12
                                    height: 20
                                    Label {
                                        id: spellQuit
                                        anchors.centerIn: parent
                                        text: "退出"
                                        font.pixelSize: 11
                                        color: root.muted
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: bridge.reviewSpellClose()
                                    }
                                }
                            }

                            //: **只显示中文**。音标、词性、档位一律不给 —— 音标基本
                            //: 等于答案（`/əˈkædəmi/` 摆在那儿就不用默写了）。
                            Label {
                                Layout.fillWidth: true
                                Layout.topMargin: 10
                                text: bridge.reviewCard.meaning || ""
                                font.pixelSize: 19
                                font.bold: true
                                color: root.ink
                                wrapMode: Text.Wrap
                                horizontalAlignment: Text.AlignHCenter
                            }
                            Label {
                                Layout.fillWidth: true
                                text: "按上面的中文写出英文单词"
                                font.pixelSize: 11
                                color: root.muted
                                horizontalAlignment: Text.AlignHCenter
                            }

                            TextField {
                                id: spellInput
                                Layout.fillWidth: true
                                Layout.topMargin: 8
                                placeholderText: "在这里输入…"
                                font.pixelSize: 18
                                horizontalAlignment: TextInput.AlignHCenter
                                //: 文字/光标颜色必须显式给：默认是系统前景色，
                                //: 夜间主题下会是黑字配深底（等于看不见）。
                                color: root.ink
                                placeholderTextColor: root.muted
                                selectionColor: root.accent
                                selectedTextColor: root.primaryFg
                                leftPadding: 12
                                rightPadding: 12
                                topPadding: 8
                                bottomPadding: 8
                                //: 焦点必须**声明式**地跟着 `open` 走：
                                //: 只在 `onVisibleChanged` 里 `forceActiveFocus()`
                                //: 不够 —— 那一刻面板/遮罩上还有别的 focus 绑定在
                                //: 重算，焦点会被抢回去，用户就打不进字（回车于是
                                //: 直接冒到 reviewPanel 上判了「记住了」）。
                                focus: bridge.reviewSpell.open === true
                                //: 判对之后锁输入：再改也没意义，还会让人以为能重判
                                readOnly: bridge.reviewSpell.verdict === "correct"
                                //: 回车 = 点右边那颗主按钮：没判对是「完成默写」，
                                //: 判对后按钮变「完成」，回车就收掉弹层。
                                //: **挂在 Keys 而不是 `onAccepted`**：Keys 默认
                                //: `BeforeItem` 优先级，先于 TextField 自己的处理
                                //: 执行，`readOnly` 之后也照样收得到；`accepted`
                                //: 置 true 顺便拦住冒泡，不然 Panel 那边还会跟着
                                //: 判一次「记住了」。
                                Keys.onReturnPressed: {
                                    event.accepted = true
                                    if (bridge.reviewSpell.verdict === "correct")
                                        bridge.reviewSpellClose()
                                    else
                                        bridge.reviewSpellSubmit(text)
                                }
                                background: Rectangle {
                                    radius: 9
                                    color: root.card
                                    border.width: 1
                                    border.color: bridge.reviewSpell.verdict === "wrong"
                                                  ? root.dangerColor : root.line
                                }
                            }

                            Label {
                                Layout.fillWidth: true
                                Layout.topMargin: 2
                                visible: (bridge.reviewSpell.verdict || "") !== ""
                                text: {
                                    var s = bridge.reviewSpell
                                    if (s.verdict === "empty")
                                        return "还没输入。"
                                    if (s.verdict === "correct")
                                        return "✓ 拼写正确"
                                    return "✗ 正确拼写：" + (s.answer || "")
                                }
                                font.pixelSize: 14
                                font.bold: bridge.reviewSpell.verdict === "correct"
                                color: bridge.reviewSpell.verdict === "correct"
                                       ? root.success
                                       : bridge.reviewSpell.verdict === "empty"
                                         ? root.muted : root.dangerColor
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.Wrap
                            }
                            Label {
                                Layout.fillWidth: true
                                visible: (bridge.reviewSpell.hint || "") !== ""
                                text: bridge.reviewSpell.hint || ""
                                font.pixelSize: 11
                                color: root.muted
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.Wrap
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Layout.topMargin: 8
                                spacing: 8
                                Item { Layout.fillWidth: true }
                                //: 判错不换按钮：输入框还开着，改完直接再点一次。
                                //: 「再写一次」那种按钮只是把同一件事多做一步。
                                MiniButton {
                                    visible: bridge.reviewSpell.verdict !== "correct"
                                    text: "完成默写"
                                    primary: true
                                    enabled: (spellInput.text || "").trim() !== ""
                                    onClicked: bridge.reviewSpellSubmit(spellInput.text)
                                }
                                MiniButton {
                                    visible: bridge.reviewSpell.verdict === "correct"
                                    text: "完成"
                                    primary: true
                                    onClicked: bridge.reviewSpellClose()
                                }
                                Item { Layout.fillWidth: true }
                            }
                        }
                    }
                }
            }

            // ---- 产品教学（右下角 ? 入口）
            Rectangle {
                id: helpPanel
                objectName: "helpPanel"
                visible: root.overlay === "help"
                width: 720
                height: helpPanel.collapsed ? root.overlayBarHeight : 540
                clip: true
                radius: 16
                color: root.card
                border.color: root.overlayPinned ? root.accent : root.line
                border.width: 1

                //: 标记 / 收起状态（见 skinsPanel 的注释）
                property bool isPanel: true
                property bool collapsed: false

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.AllButtons
                    onWheel: function(wheel) { wheel.accepted = true }
                }
                DragBar {
                    panel: helpPanel
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 6
                    height: 38
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 10
                    RowLayout {
                        Label {
                            text: "怎么用词蛛"
                            font.pixelSize: 15
                            font.bold: true
                            color: root.ink
                        }
                        Item { Layout.fillWidth: true }
                        Label {
                            text: "标「开发中」的部分还没上线"
                            font.pixelSize: 11
                            color: root.muted
                        }
                        WinButton {
                            glyph: helpPanel.collapsed ? "\u25A1" : "\u2014"
                            onClicked: root.toggleOverlayCollapsed(helpPanel)
                        }
                        WinButton { glyph: "\u2715"; onClicked: root.overlay = "" }
                    }

                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true

                        ColumnLayout {
                            width: helpPanel.width - 40
                            spacing: 10
                            Repeater {
                                model: bridge.helpSteps
                                delegate: Rectangle {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    height: stepCol.implicitHeight + 20
                                    radius: 11
                                    color: root.panelAlt
                                    border.color: root.line
                                    border.width: 1
                                    ColumnLayout {
                                        id: stepCol
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 6
                                        RowLayout {
                                            spacing: 8
                                            Label {
                                                text: modelData.icon
                                                font.pixelSize: 13
                                                color: root.accent
                                            }
                                            Label {
                                                text: modelData.title
                                                font.pixelSize: 14
                                                font.bold: true
                                                color: root.ink
                                            }
                                            Label {
                                                visible: modelData.stateLabel !== ""
                                                text: modelData.stateLabel
                                                font.pixelSize: 11
                                                color: modelData.state === "planned"
                                                       ? root.white : root.warnColor
                                                leftPadding: 6; rightPadding: 6
                                                topPadding: 2; bottomPadding: 2
                                                background: Rectangle {
                                                    radius: 5
                                                    color: modelData.state === "planned"
                                                           ? root.subtleColor : root.warnChip
                                                }
                                            }
                                            Item { Layout.fillWidth: true }
                                        }
                                        Label {
                                            visible: modelData.note !== ""
                                            Layout.fillWidth: true
                                            text: modelData.note
                                            font.pixelSize: 12
                                            color: root.warnColor
                                            wrapMode: Text.Wrap
                                        }
                                        Repeater {
                                            model: modelData.bullets
                                            delegate: RowLayout {
                                                required property var modelData
                                                Layout.fillWidth: true
                                                spacing: 7
                                                Label {
                                                    text: "·"
                                                    font.pixelSize: 13
                                                    color: root.muted
                                                    Layout.preferredWidth: 8
                                                    Layout.alignment: Qt.AlignTop
                                                }
                                                Label {
                                                    Layout.fillWidth: true
                                                    text: modelData
                                                    font.pixelSize: 12
                                                    color: root.text
                                                    wrapMode: Text.Wrap
                                                }
                                            }
                                        }
                                        RowLayout {
                                            visible: modelData.id === "api"
                                            MiniButton {
                                                text: "打开配置"
                                                primary: true
                                                onClicked: root.overlay = "api"
                                            }
                                        }
                                        RowLayout {
                                            visible: modelData.id === "review"
                                            MiniButton {
                                                text: "开始背单词"
                                                primary: true
                                                onClicked: {
                                                    bridge.openReview()
                                                    root.overlay = "review"
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // ------------------------------------------------ 成就弹窗（§7.3 / §7.4）
        // 每次「首次达成」才出现；关闭/保存后由 bridge 标记已读，不会重复弹。
        // 覆盖在覆盖层之上（z 更高），但要能独立于 overlay 状态存在。
        Item {
            id: achievementLayer
            anchors.fill: parent
            z: 300
            visible: (bridge.achievement && bridge.achievement.id)
                     ? bridge.achievement.id !== "" : false

            Rectangle {
                anchors.fill: parent
                color: root.scrim
                MouseArea { anchors.fill: parent }   // 吃掉点击，不落到主界面
            }

            Rectangle {
                width: Math.min(460, parent.width - 80)
                height: achieveCol.implicitHeight + 44
                anchors.centerIn: parent
                radius: 18
                color: root.card
                border.color: root.line
                border.width: 1

                ColumnLayout {
                    id: achieveCol
                    anchors.fill: parent
                    anchors.margins: 22
                    spacing: 8

                    Label {
                        text: "成就达成"
                        font.pixelSize: 11
                        color: root.accent
                        font.bold: true
                    }
                    Label {
                        Layout.fillWidth: true
                        text: (bridge.achievement.name || "成就达成")
                        font.pixelSize: 24
                        font.bold: true
                        color: root.ink
                        wrapMode: Text.Wrap
                    }
                    Label {
                        Layout.fillWidth: true
                        text: (bridge.achievement.desc || "")
                        font.pixelSize: 12
                        color: root.muted
                        wrapMode: Text.Wrap
                    }
                    Label {
                        Layout.fillWidth: true
                        text: (bridge.achievement.cheer || "")
                        font.pixelSize: 13
                        color: root.text
                        wrapMode: Text.Wrap
                        Layout.topMargin: 4
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "达成日期 " + (bridge.achievement.date || "")
                              + ((bridge.achievement.total || 0) > 1
                                 ? ("　·　还有 " + (bridge.achievement.total - 1)
                                    + " 个待展示") : "")
                        font.pixelSize: 11
                        color: root.subtleColor
                        wrapMode: Text.Wrap
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.topMargin: 6
                        height: 1
                        color: root.line
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "是否保存当前学习日历图片？"
                        font.pixelSize: 12
                        color: root.ink
                        wrapMode: Text.Wrap
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "图片只包含日历格子、日期范围、打卡天数和图例，"
                              + "不会带出设置或桌面内容。"
                        font.pixelSize: 10
                        color: root.muted
                        wrapMode: Text.Wrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 4
                        spacing: 8
                        Item { Layout.fillWidth: true }
                        MiniButton {
                            text: "暂不保存"
                            onClicked: bridge.dismissAchievement(false)
                        }
                        MiniButton {
                            text: "保存图片"
                            primary: true
                            onClicked: bridge.dismissAchievement(true)
                        }
                    }
                }
            }
        }

        // ------------------------------------------------ 边缘拉伸（8 个方向）
        // 放在 shell 内部：QML 文档只允许一个根对象，边缘件必须是它的子项；
        // 声明在最后 → 天然压在其它内容之上，优先吃到边缘的鼠标事件。
        component EdgeResize: MouseArea {
            property int edges: 0
            onPressed: function (mouse) {
                if (mouse.buttons & Qt.LeftButton)
                    root.startSystemResize(edges)
            }
        }
        EdgeResize {
            edges: Qt.LeftEdge
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: 6
            cursorShape: Qt.SizeHorCursor
        }
        EdgeResize {
            edges: Qt.RightEdge
            anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
            width: 6
            cursorShape: Qt.SizeHorCursor
        }
        EdgeResize {
            edges: Qt.TopEdge
            anchors { top: parent.top; left: parent.left; right: parent.right }
            height: 4
            cursorShape: Qt.SizeVerCursor
        }
        EdgeResize {
            edges: Qt.BottomEdge
            anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
            height: 6
            cursorShape: Qt.SizeVerCursor
        }
        EdgeResize {
            edges: Qt.LeftEdge | Qt.TopEdge
            anchors { left: parent.left; top: parent.top }
            width: 10; height: 10
            cursorShape: Qt.SizeFDiagCursor
        }
        EdgeResize {
            edges: Qt.RightEdge | Qt.BottomEdge
            anchors { right: parent.right; bottom: parent.bottom }
            width: 10; height: 10
            cursorShape: Qt.SizeFDiagCursor
        }
        EdgeResize {
            edges: Qt.LeftEdge | Qt.BottomEdge
            anchors { left: parent.left; bottom: parent.bottom }
            width: 10; height: 10
            cursorShape: Qt.SizeBDiagCursor
        }
        EdgeResize {
            edges: Qt.RightEdge | Qt.TopEdge
            anchors { right: parent.right; top: parent.top }
            width: 10; height: 10
            cursorShape: Qt.SizeBDiagCursor
        }
    }

    // ------------------------------------------------ 复用小组件
    //: 侧栏动作行。`big` 用于底部「换皮肤 / 设置」—— 图标 18→36、文字 13→20、
    //: 行高 38→56，视觉上约 2 倍（点击热区同步放大，不会只放大字不放大可点区域）。
    component SideAction: AbstractButton {
        id: sa
        property string iconChar: ""
        property string label: ""
        property string iconSource: ""
        property bool big: false
        readonly property int box: big ? 40 : 20
        readonly property int glyph: big ? 34 : 18
        Layout.fillWidth: true
        implicitHeight: big ? 56 : 40
        opacity: hovered ? 1.0 : (big ? 1.0 : 0.92)
        contentItem: RowLayout {
            spacing: big ? 12 : 9
            Item {
                Layout.preferredWidth: sa.box
                Layout.preferredHeight: sa.box
                Image {
                    anchors.centerIn: parent
                    visible: sa.iconSource !== ""
                    source: sa.iconSource
                    sourceSize.width: sa.glyph
                    sourceSize.height: sa.glyph
                    smooth: true
                }
                Label {
                    anchors.centerIn: parent
                    visible: sa.iconSource === ""
                    text: sa.iconChar
                    font.pixelSize: big ? 22 : 13
                    color: root.muted
                }
            }
            Label {
                text: sa.label
                font.pixelSize: sa.big ? 20 : 13
                font.bold: sa.big
                color: sa.big ? root.ink : root.text
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignLeft
                verticalAlignment: Text.AlignVCenter
            }
        }
        background: Rectangle {
            radius: 11
            color: sa.hovered ? root.navHoverBg : "transparent"
        }
    }

    //: 覆盖面板标题栏的拖动条：按住拖，双击回中间。
    //:
    //: 为什么做成一个组件：6 个面板各贴一遍 MouseArea 的话，「拖动时转浮动」
    //: 「松手夹回窗口内」这种细节总会有人漏，改一次得改 6 处。
    //:
    //: ★ 它必须与面板的内容 ColumnLayout **平级**，绝不能塞进标题的 RowLayout：
    //:   Layout 会接管子项的 x/y/width/height，anchors 直接被忽略（还会刷警告）。
    component DragBar: MouseArea {
        id: dragBar
        property Item panel: null
        acceptedButtons: Qt.LeftButton
        cursorShape: Qt.OpenHandCursor
        drag.target: panel
        drag.axis: Drag.XAndYAxis
        onPressed: dragBar.cursorShape = Qt.ClosedHandCursor
        onReleased: {
            dragBar.cursorShape = Qt.OpenHandCursor
            root.clampOverlay(dragBar.panel)
        }
        onPositionChanged: {
            // 真的拖了才转浮动：只是点一下标题栏不该把遮罩撤掉
            if (dragBar.drag.active)
                root.overlayPinned = true
        }
    }

    component WinButton: AbstractButton {
        id: wb
        property string glyph: ""
        property string hoverBg: root.hover
        property string hoverFg: root.ink
        //: 常态前景色（标题带压在墨绿上时要传浅色，默认仍是墨色）
        property string fg: root.muted
        implicitWidth: 30
        implicitHeight: 30
        contentItem: Label {
            text: wb.glyph
            font.pixelSize: 12
            color: wb.hovered ? wb.hoverFg : wb.fg
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 8
            color: wb.hovered ? wb.hoverBg : "transparent"
        }
    }

    // ``tone``: normal | warning —— 未配置这类需要被看见的状态用醒目标记，
    // 但**不只靠颜色**传达（文字本身就写明了「API 未配置」）。
    component PillButton: Button {
        id: pb
        property string tone: "normal"
        implicitHeight: 26
        implicitWidth: Math.max(40, pbText.implicitWidth + 22)
        contentItem: Label {
            id: pbText
            text: pb.text
            font.pixelSize: 12
            color: pb.checked ? root.accent
                 : pb.tone === "warning" ? root.pillWarnFg : root.muted
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 13
            color: pb.checked ? root.accentSoft
                 : pb.hovered ? root.hover : "transparent"
            border.color: pb.checked ? root.accent
                        : pb.tone === "warning" ? root.pillWarnBorder : root.line
            border.width: 1
        }
    }

    //: 设置面板里的一行「标签 + 滑杆 + 数值」。滑杆自身不带业务状态，
    //: 只在用户拖动（onMoved）时发 activated，避免程序化赋值回环。
    component ValueSlider: RowLayout {
        id: vs
        property string label: ""
        property string unit: ""
        property int from: 0
        property int to: 100
        property int stepSize: 1
        property int value: 0
        signal activated(int value)
        spacing: 8

        Label {
            text: vs.label
            font.pixelSize: 12
            color: root.text
            Layout.preferredWidth: 78
        }
        Slider {
            id: ctl
            Layout.fillWidth: true
            Layout.preferredHeight: 26
            from: vs.from
            to: vs.to
            stepSize: vs.stepSize
            onMoved: vs.activated(Math.round(ctl.value))
            background: Rectangle {
                x: ctl.leftPadding
                y: ctl.topPadding + ctl.availableHeight / 2 - height / 2
                implicitWidth: 200
                implicitHeight: 4
                width: ctl.availableWidth
                height: 4
                radius: 2
                color: root.line
                Rectangle {
                    width: ctl.visualPosition * parent.width
                    height: parent.height
                    radius: 2
                    color: root.accent
                }
            }
            handle: Rectangle {
                x: ctl.leftPadding + ctl.visualPosition * (ctl.availableWidth - width)
                y: ctl.topPadding + ctl.availableHeight / 2 - height / 2
                width: 16
                height: 16
                radius: 8
                color: root.white
                border.color: root.accent
                border.width: 1.5
            }
        }
        Binding {
            target: ctl
            property: "value"
            value: vs.value
            when: !ctl.pressed
        }
        Label {
            text: Math.round(ctl.value) + vs.unit
            font.pixelSize: 12
            color: root.muted
            Layout.preferredWidth: 48
            horizontalAlignment: Text.AlignRight
        }
    }

    //: 轻量文字/次按钮。`primary` 用于本视图唯一主操作，`danger` 用于破坏性操作。
    //: 三者都保留文字标签，不靠颜色单独区分语义。
    component MiniButton: Button {
        id: mb
        property bool primary: false
        property bool danger: false
        implicitWidth: Math.max(64, mbLabel.implicitWidth + 24)
        implicitHeight: 32
        opacity: mb.enabled ? 1 : 0.45
        contentItem: Label {
            id: mbLabel
            text: mb.text
            font.pixelSize: 12
            color: !mb.enabled ? root.subtleColor
                 : mb.primary ? root.primaryFg
                 : mb.danger ? root.dangerColor : root.text
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 9
            color: !mb.enabled ? root.card
                 : mb.primary ? root.accent
                 : mb.hovered ? root.hover : root.card
            border.width: mb.primary ? 0 : 1
            border.color: mb.danger ? root.dangerBorder : root.line
        }
    }

    //: 复习入口页 / 完成页的数字块。数字直接用真实统计，不让 UI 编造。
    component ReviewStat: Rectangle {
        id: rs
        property string value: "0"
        property string label: ""
        property bool highlight: false
        property bool warn: false
        implicitHeight: 74
        radius: 11
        color: rs.highlight ? root.accentSoft
             : rs.warn ? root.dangerSoft : root.panel
        border.color: rs.highlight ? root.accent
                    : rs.warn ? root.dangerLine : root.line
        border.width: 1
        ColumnLayout {
            anchors.centerIn: parent
            spacing: 2
            Label {
                Layout.alignment: Qt.AlignHCenter
                text: rs.value
                font.pixelSize: 21
                font.bold: true
                color: rs.highlight ? root.accent
                     : rs.warn ? root.warnColor : root.ink
            }
            Label {
                Layout.alignment: Qt.AlignHCenter
                text: rs.label
                font.pixelSize: 11
                color: root.muted
            }
        }
    }

    component MiniSwitch: Item {
        id: sw
        property bool checked: false
        signal toggled(bool value)
        implicitWidth: 40
        implicitHeight: 22
        // 系统不支持（比如非 Windows）或条件不满足时置灰，点击无效
        opacity: sw.enabled ? 1.0 : 0.4

        Rectangle {
            anchors.fill: parent
            radius: 11
            color: sw.checked ? root.accent : root.switchOff
            Behavior on color { ColorAnimation { duration: 120 } }
            Rectangle {
                width: 18
                height: 18
                radius: 9
                y: 2
                x: sw.checked ? parent.width - 20 : 2
                color: root.white
                Behavior on x { NumberAnimation { duration: 120 } }
            }
        }
        MouseArea {
            anchors.fill: parent
            enabled: sw.enabled
            cursorShape: Qt.PointingHandCursor
            onClicked: sw.toggled(!sw.checked)
        }
    }
}
