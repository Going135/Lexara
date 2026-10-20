# -*- coding: utf-8 -*-
"""界面：识词结果卡、单词本 + 复习、识词模式设置。

统一 LEXARA 极简桌面主题：暖白/纯白实体表面 + 单一品牌蓝焦点，与启动台保持同一视觉语言。
"""

from __future__ import annotations

import random

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout,
                               QWidget)

import content
import lexicon
import settings_store
#: 「八足微光」八色。**必须和腿、词框同源**：卡片左侧那道小色条就是
#: 「踩住这个词的那条腿」的颜色，用户靠它把卡片里的词和屏幕上的框对起来。
#: 直接从 `crawler_spider` 取，别再在界面层抄一份常量 —— 抄一次就会漂一次，
#: 之前这里被写成 `("#2F6BFF",) * 8`，八个色条全成了品牌蓝。
from crawler_spider import LEG_AURA
from lexara_theme import DIALOG_QSS
from review_session import ReviewSession


BOOKMARK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="#2F6BFF" stroke-width="1.8" stroke-linejoin="round">'
    '<path d="M7 4.5h10a1 1 0 0 1 1 1V20l-6-3.6L6 20V5.5a1 1 0 0 1 1-1z"/></svg>'
)
BOOKMARK_FILLED_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<path fill="#2F6BFF" d="M7 4.5h10a1 1 0 0 1 1 1V20l-6-3.6L6 20V5.5a1 1 0 0 1 1-1z"/></svg>'
)
REFRESH_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="#2B2B2B" stroke-width="1.8" stroke-linecap="round">'
    '<path d="M20 11a8 8 0 0 0-14.7-4L4 9"/><path d="M4 5v4h4"/>'
    '<path d="M4 13a8 8 0 0 0 14.7 4L20 15"/><path d="M20 19v-4h-4"/></svg>'
)

def _svg_icon(svg: str, size: int = 18) -> QIcon:
    """内联 SVG → QIcon，避免不同 Windows 字体造成图标跳变。"""
    try:
        from PySide6.QtSvg import QSvgRenderer
        image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(
            painter, QRectF(0, 0, size, size))
        painter.end()
        return QIcon(QPixmap.fromImage(image))
    except Exception:  # noqa: BLE001
        return QIcon()

QSS = DIALOG_QSS


def _badge(text: str, off: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName("off" if off else "badge")
    return label


def _set_bookmark(button: QPushButton, on: bool) -> None:
    """收藏状态只切换图标与样式，不改变原有点击逻辑。"""
    button.setObjectName("starOn" if on else "star")
    button.setIcon(_svg_icon(BOOKMARK_FILLED_SVG if on else BOOKMARK_SVG, 18))
    button.setIconSize(QSize(18, 18))
    button.setText("")
    button.setStyleSheet("")
    button.style().unpolish(button)
    button.style().polish(button)


def _enable_button_cursors(widget: QWidget) -> None:
    for button in widget.findChildren(QPushButton):
        button.setCursor(Qt.PointingHandCursor)


class WordResultDialog(QDialog):
    """框选识词结果：本地词典先把释义摆出来，AI 语境分析**点了才发**。

    任务书 §5.1/§5.2 的 UI 落点：
    * 卡片进来时只有词典内容，一次网络请求都没发；
    * 每张卡右侧的「AI 语境分析与造句」是**唯一**的云端入口；
    * 整张卡同一时刻只允许一个在途请求（限流），按钮在请求中变成「取消」；
    * 未配置 → 直接提示「先配置 API/模型」，不会拿着空 key 去撞 401；
    * 失败 → 保留本地释义，只在这张卡下面写一行原因 + 可重试；
    * 关闭卡片 → 取消并等待后台线程，不留幽灵请求。
    """

    def __init__(self, parent, items, wordbook, mode_label=""):
        super().__init__(parent)
        self.setWindowTitle("微光识词")
        self.setStyleSheet(QSS)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.items = items
        self.book = wordbook
        self._stars = {}
        self._aura = {}
        #: lemma → 卡片上的 AI 控件集合
        self._ai_ui = {}
        #: 当前在途请求（整卡共享一个，天然限流）
        self._ai_request = None
        self._ai_word = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("微光从屏幕里挑出的单词")
        title.setObjectName("title")
        root.addWidget(title)

        sub_text = f"共 {len(items)} 个"
        stats = self.book.stats()
        sub_text += f"　·　今日学习 {stats.get('today', 0)} 个"
        if mode_label:
            sub_text += f"　·　模式：{mode_label}"
        sub_text += "　·　点右侧书签收藏到单词本"
        sub = QLabel(sub_text)
        sub.setObjectName("sub")
        root.addWidget(sub)

        ai_items = [item for item in items if item.get("ai_source")]
        if ai_items:
            candidate_count = ai_items[0].get("ai_candidate_count", len(items))
            source = ai_items[0].get("ai_source")
            if source == "local":
                # §5.1 默认路径：这一段必须如实写「没有联网」。
                text = ("本地词典　·　识别候选 %d　→　出卡 %d　·　未调用云端，"
                        "点卡片里的「AI 语境分析与造句」才会请求模型"
                        % (candidate_count, len(ai_items)))
            else:
                text = ("AI 学习分析　·　识别候选 %d　→　推荐 %d　·　%s"
                        % (candidate_count, len(ai_items),
                           "云端 AI" if source == "cloud" else "本地规则"))
            analysis = QLabel(text)
            analysis.setObjectName("analysis")
            root.addWidget(analysis)

        area = QScrollArea()
        area.setWidgetResizable(True)
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(8)
        for index, item in enumerate(items):
            layout.addWidget(self._card(item, index))
        layout.addStretch(1)
        area.setWidget(holder)
        root.addWidget(area, 1)

        buttons = QHBoxLayout()
        b_all = QPushButton("全部收藏")
        b_all.setObjectName("primary")
        b_all.clicked.connect(self._collect_all)
        b_close = QPushButton("关闭")
        b_close.clicked.connect(self.close)
        buttons.addWidget(b_all)
        buttons.addStretch(1)
        buttons.addWidget(b_close)
        root.addLayout(buttons)

        self.resize(480, 520)
        _enable_button_cursors(self)

    def _card(self, item: dict, index: int) -> QFrame:
        # 色号由覆盖层写进 `item["aura"]`（腿踩上来的那个色）；没有就按词序取一档，
        # 与词框的兜底规则完全一致，绝不再固定成品牌蓝。
        aura = item.get("aura") or LEG_AURA[index % len(LEG_AURA)]
        self._aura[item["lemma"]] = aura

        card = QFrame()
        card.setObjectName("card")

        row = QHBoxLayout(card)
        row.setContentsMargins(12, 10, 10, 10)
        row.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(3)
        head = QHBoxLayout()
        head.setSpacing(8)

        # 卡片左侧的小色条，和踩住这个词的那条腿、屏幕上的词框同色
        swatch = QFrame()
        swatch.setFixedSize(3, 22)
        swatch.setStyleSheet(
            "background: %s; border-radius: 1px;" % aura)
        head.addWidget(swatch)

        word = QLabel(item["lemma"])
        word.setObjectName("word")
        head.addWidget(word)

        if item.get("phonetic"):
            phon = QLabel(item["phonetic"])
            phon.setObjectName("phon")
            head.addWidget(phon)

        if item.get("level"):
            head.addWidget(_badge(item["level"]))
        if item.get("off_syllabus"):
            head.addWidget(_badge("词表外", off=True))
        if item.get("surface") and item["surface"] != item["lemma"]:
            note = QLabel("原文 %s" % item["surface"])
            note.setObjectName("sub")
            head.addWidget(note)

        head.addStretch(1)
        left.addLayout(head)

        meaning = QLabel(item.get("meaning") or "（词典里没有中文释义）")
        meaning.setObjectName("mean")
        meaning.setWordWrap(True)
        left.addWidget(meaning)
        if item.get("ai_source") in ("cloud", "rules"):
            # 只有真的跑过云端（或云端失败后的规则兜底）才显示这一段。
            # `local` 的 `context_meaning` 就是上面那行词典释义本身，
            # 再重复一遍只会让卡片变长。
            source = "AI 语境解释" if item["ai_source"] == "cloud" else "本地规则 · 词典释义"
            details = QLabel(source)
            details.setObjectName("sub")
            left.addWidget(details)
            explanation = QLabel(item.get("context_meaning", ""))
            explanation.setTextFormat(Qt.PlainText)
            explanation.setWordWrap(True)
            left.addWidget(explanation)
            reason = QLabel(item.get("ai_reason", ""))
            reason.setTextFormat(Qt.PlainText)
            reason.setObjectName("sub")
            reason.setWordWrap(True)
            left.addWidget(reason)
            context = QLabel(item.get("context_sentence", ""))
            context.setWordWrap(True)
            context.setObjectName("sub")
            context.setTextFormat(Qt.PlainText)
            left.addWidget(context)
            if item.get("collocations"):
                phrases = QLabel("常见搭配：" + " / ".join(item["collocations"]))
                phrases.setWordWrap(True)
                phrases.setTextFormat(Qt.PlainText)
                left.addWidget(phrases)

        # ---- AI 按需入口（默认不发请求）-----------------------------------
        ai_box = QFrame()
        ai_box.setObjectName("aiBox")
        ai_box.setVisible(False)
        ai_layout = QVBoxLayout(ai_box)
        ai_layout.setContentsMargins(10, 8, 10, 8)
        ai_layout.setSpacing(4)
        ai_labels = {}
        for key, name in (("context", "mean"), ("reason", "sub"),
                          ("phrases", "sub"), ("examples", "sub")):
            label = QLabel("")
            label.setObjectName(name)
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            ai_layout.addWidget(label)
            ai_labels[key] = label

        ai_row = QHBoxLayout()
        ai_row.setSpacing(8)
        ai_button = QPushButton("AI 语境分析与造句")
        ai_button.setAccessibleName("AI 语境分析与造句")
        ai_button.setToolTip("把这个词所在的 OCR 句子和词典义项发给已配置的模型；"
                             "不发送截图。")
        ai_status = QLabel("")
        ai_status.setObjectName("sub")
        ai_status.setWordWrap(True)
        ai_row.addWidget(ai_button, 0, Qt.AlignLeft)
        ai_row.addWidget(ai_status, 1)
        left.addLayout(ai_row)
        left.addWidget(ai_box)
        self._ai_ui[item["lemma"]] = {
            "item": item, "button": ai_button, "status": ai_status,
            "box": ai_box, "labels": ai_labels}
        ai_button.clicked.connect(
            lambda _, lemma=item["lemma"]: self._on_ai_clicked(lemma))

        row.addLayout(left, 1)

        star = QPushButton()
        starred = self.book.has(item["lemma"])
        _set_bookmark(star, starred)
        star.setAccessibleName("收藏到单词本")
        star.setToolTip("收藏到单词本")
        star.clicked.connect(lambda _, i=item, b=star: self._toggle(i, b))
        row.addWidget(star, 0, Qt.AlignTop)
        self._stars[item["lemma"]] = star
        return card

    # ------------------------------------------------ AI 语境分析（点了才发）
    def _on_ai_clicked(self, lemma: str) -> None:
        """按钮的唯一入口：请求中再点=取消；别的卡有点=排队等限流。"""
        ui = self._ai_ui.get(lemma)
        if ui is None:
            return
        request = self._ai_request
        if request is not None and request.active:
            if self._ai_word == lemma:
                ui["button"].setText("正在取消…")
                ui["button"].setEnabled(False)
                request.cancel()
                return
            ui["status"].setText("已经有一个分析在跑了，等它结束再点。")
            return
        self._request_ai(lemma, ui)

    def _request_ai(self, lemma: str, ui: dict) -> None:
        from ai.context_request import ContextRequest
        item = ui["item"]
        request = ContextRequest(parent=self)
        self._ai_request = request
        self._ai_word = lemma
        request.finished.connect(
            lambda result, key=lemma: self._ai_finished(key, result))
        ui["button"].setText("取消")
        ui["button"].setEnabled(True)
        ui["status"].setText("正在分析　·　只发送这句话和词典释义，不发送截图")
        ui["box"].setVisible(False)
        # 「未配置」是一条**同步**的 finished：上面先连好了槽，所以这里
        # 不需要额外处理返回值，卡片也不会停在 loading。
        request.start(item, item.get("context_sentence", ""))

    def _ai_finished(self, lemma: str, result: dict) -> None:
        ui = self._ai_ui.get(lemma)
        self._ai_request = None
        if ui is None:                      # 对话框已经关了/卡片重建过
            return
        # 取消是在 `closeEvent` 里发起的，排队信号可能在卡片析构**之后**才送到。
        # 碰到已经没了的 C++ 对象就直接收工，别让 RuntimeError 把进程带下去。
        try:
            from shiboken6 import isValid
            if not isValid(ui["button"]):
                return
        except Exception:                    # noqa: BLE001
            pass
        status = result.get("status")
        ui["button"].setEnabled(True)
        if status == "ok":
            ai = result.get("ai") or {}
            labels = ui["labels"]
            labels["context"].setText("句中义　·　" + ai.get("context_meaning", ""))
            labels["reason"].setText(ai.get("ai_reason", ""))
            phrases = ai.get("collocations") or []
            labels["phrases"].setText("常见搭配：" + " / ".join(phrases)
                                      if phrases else "")
            examples = ai.get("examples") or []
            labels["examples"].setText(
                "例句：\n" + "\n".join("· %s\n   %s" % (e["sentence"], e["meaning"])
                                       for e in examples) if examples else "")
            ui["box"].setVisible(True)
            ui["status"].setText(
                "云端语境分析完成 · 用时 %.1fs　·　词典释义与词框未改动"
                % float(result.get("elapsed") or 0))
            ui["button"].setText("再分析一次")
            # 结果并回词卡，收藏时一起带走；只覆盖 `ai_*`/`context_*`，
            # `word/lemma/surface/meaning/screen_box` 一个都不动（§5.4）。
            ui["item"].update(ai)
        elif status == "unconfigured":
            ui["box"].setVisible(False)
            ui["status"].setText("先配置 API/模型　·　" + result.get("message", ""))
            ui["button"].setText("AI 语境分析与造句")
        elif status == "cancelled":
            ui["box"].setVisible(False)
            ui["status"].setText("已取消　·　本地释义不受影响")
            ui["button"].setText("AI 语境分析与造句")
        else:
            ui["box"].setVisible(False)
            ui["status"].setText("分析失败：%s" % result.get("message", "请求没有成功"))
            ui["button"].setText("重试 AI 分析")

    def closeEvent(self, event) -> None:
        """关卡片时把在途请求收干净，不留后台线程（§5.3 / §7 的清理要求）。"""
        request = self._ai_request
        if request is not None:
            request.cancel()
        self._ai_request = None
        super().closeEvent(event)

    def _toggle(self, item: dict, button: QPushButton) -> None:
        if self.book.has(item["lemma"]):
            self.book.remove(item["lemma"])
            on = False
        else:
            self.book.add(item)
            on = True
        _set_bookmark(button, on)

    def _collect_all(self) -> None:
        added = 0
        for item in self.items:
            if self.book.add(item):
                added += 1
            button = self._stars.get(item["lemma"])
            if button:
                _set_bookmark(button, True)
        if added == 0:
            QMessageBox.information(self, "单词本", "这些词已经都在单词本里了。")


class WordbookDialog(QDialog):
    """单词本：列表 + 搜索 + 删除，以及按间隔重复调度的复习页。

    2026-10-18（任务书 §2.2）：可以带一个 ``category`` 进来，用于「收藏夹 →
    四级 / 六级 / 雅思 / 托福 / 工业英语 / 未分类」点击后只看该分类。
    过滤只影响**显示**，底层仍然是同一份收藏记录（一个词只存一条）。
    """

    def __init__(self, parent, wordbook, category: str = "", lexicon=None):
        super().__init__(parent)
        self.setWindowTitle("微光单词本")
        self.setStyleSheet(QSS)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.book = wordbook
        #: 当前分类过滤（空 = 全部）；分类键见 `lexicon.FAVORITE_CATEGORIES`
        self.category = category or ""
        #: 老收藏可能没存 tags，需要回查词典；缺词典时只按已存 tags 判断
        self.lexicon = lexicon
        # 2026-10-17：复习流程状态搬到 `review_session.ReviewSession`，
        # 新的 QML 复习页与这里共用同一个类，两边不可能 behaviour 分叉。
        # `limit=None` = 全量（旧 Widgets 复习页的原行为）。
        self.review = ReviewSession(wordbook)
        self.resize(520, 580)

        self.stack = QStackedWidget(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.addWidget(self.stack)
        self.stack.addWidget(self._build_list())
        self.stack.addWidget(self._build_review())
        self.refresh()
        _enable_button_cursors(self)

    # ------------------------------------------------ 列表页
    def _build_list(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        title = QLabel("我的单词本")
        title.setObjectName("title")
        layout.addWidget(title)

        self.count_label = QLabel("")
        self.count_label.setObjectName("sub")
        layout.addWidget(self.count_label)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索单词或释义…")
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)

        self.list = QListWidget()
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        b_review = QPushButton("开始复习")
        b_review.setObjectName("primary")
        b_review.clicked.connect(self.start_review)
        b_delete = QPushButton("删除选中")
        b_delete.clicked.connect(self._delete)
        b_clear = QPushButton("清空")
        b_clear.clicked.connect(self._clear)
        b_close = QPushButton("关闭")
        b_close.clicked.connect(self.close)
        row.addWidget(b_review)
        row.addWidget(b_delete)
        row.addWidget(b_clear)
        row.addStretch(1)
        row.addWidget(b_close)
        layout.addLayout(row)
        return page

    def category_name(self) -> str:
        from lexicon import FAVORITE_CATEGORIES, OTHER_CATEGORY
        for key, label in FAVORITE_CATEGORIES + (OTHER_CATEGORY,):
            if key == self.category:
                return label
        return ""

    def _tags_of(self, item) -> set:
        tags = set(getattr(item, "tags", []) or [])
        if tags or self.lexicon is None:
            return tags
        try:
            return set(self.lexicon.tags_of(item.word))
        except Exception:                       # noqa: BLE001
            return set()

    def _in_category(self, item) -> bool:
        """当前分类过滤。空分类 = 全部；`other` = 一个分类都不命中。"""
        if not self.category:
            return True
        from lexicon import FAVORITE_CATEGORIES
        keys = {key for key, _label in FAVORITE_CATEGORIES}
        tags = self._tags_of(item)
        if self.category == "other":
            return not (tags & keys)
        return self.category in tags

    def refresh(self) -> None:
        keyword = self.search.text().strip().lower() if hasattr(self, "search") else ""
        self.list.clear()
        shown = 0
        stats = self.book.stats()
        for item in self.book.items:
            if keyword and keyword not in item.word and keyword not in item.meaning.lower():
                continue
            if not self._in_category(item):
                continue
            flag = "待复习" if item.due else "已掌握"
            text = (f"{item.word}   {item.phonetic}\n"
                    f"{item.meaning}   [{item.level}]   {flag}")
            row = QListWidgetItem(text)
            row.setData(Qt.UserRole, item.word)
            self.list.addItem(row)
            shown += 1
        extra = f"，当前显示 {shown} 个" if keyword else ""
        label = self.category_name()
        scope = f" · {label}" if label else ""
        due = f"，今天待复习 {stats['due']} 个" if stats["due"] else ""
        today = f"，今日学习 {stats.get('today', 0)} 个" if stats.get("today") else ""
        if hasattr(self, "count_label"):
            self.count_label.setText(
                f"已收藏 {stats['total']} 个单词{scope}{extra}{due}{today}")

    def _delete(self) -> None:
        current = self.list.currentItem()
        if not current:
            return
        self.book.remove(current.data(Qt.UserRole))
        self.refresh()

    def _clear(self) -> None:
        if len(self.book) == 0:
            return
        if QMessageBox.question(self, "清空单词本",
                                "确定要清空所有收藏的单词吗？") == QMessageBox.Yes:
            self.book.clear()
            self.refresh()

    # ------------------------------------------------ 复习页
    def _build_review(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = QLabel("复习（1 / 3 / 7 / 14 天）")
        title.setObjectName("title")
        layout.addWidget(title)

        self.review_progress = QLabel("")
        self.review_progress.setObjectName("sub")
        layout.addWidget(self.review_progress)

        card = QFrame()
        card.setObjectName("card")
        card.setCursor(Qt.PointingHandCursor)
        card.setToolTip("点击卡片显示释义")
        # LEXARA review surface: plain white, strong type, almost no decoration.
        card.setStyleSheet("")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 32, 24, 32)
        card_layout.setSpacing(14)

        self.review_word = QLabel("")
        self.review_word.setObjectName("word")
        self.review_word.setAlignment(Qt.AlignCenter)
        self.review_phon = QLabel("")
        self.review_phon.setObjectName("phon")
        self.review_phon.setAlignment(Qt.AlignCenter)
        self.review_mean = QLabel("")
        self.review_mean.setObjectName("mean")
        self.review_mean.setAlignment(Qt.AlignCenter)
        self.review_mean.setWordWrap(True)
        self.review_tip = QLabel("点击卡片显示释义")
        self.review_tip.setObjectName("sub")
        self.review_tip.setAlignment(Qt.AlignCenter)

        card_layout.addStretch(1)
        card_layout.addWidget(self.review_word)
        card_layout.addWidget(self.review_phon)
        card_layout.addWidget(self.review_mean)
        card_layout.addWidget(self.review_tip)
        card_layout.addStretch(1)
        card.mousePressEvent = lambda event: self.reveal()
        layout.addWidget(card, 1)

        row = QHBoxLayout()
        b_prev = QPushButton("上一个")
        b_prev.clicked.connect(lambda: self.step(-1))
        b_show = QPushButton("显示释义")
        b_show.clicked.connect(self.reveal)
        self.b_again = QPushButton("不会")
        self.b_again.clicked.connect(lambda: self._grade(False))
        self.b_known = QPushButton("记住了")
        self.b_known.setObjectName("primary")
        self.b_known.clicked.connect(lambda: self._grade(True))
        b_back = QPushButton("返回列表")
        b_back.clicked.connect(self._back_to_list)
        row.addWidget(b_prev)
        row.addWidget(b_show)
        row.addWidget(self.b_again)
        row.addWidget(self.b_known)
        row.addStretch(1)
        row.addWidget(b_back)
        layout.addLayout(row)
        return page

    def start_review(self) -> None:
        if len(self.book) == 0:
            QMessageBox.information(self, "单词本", "单词本还是空的，先去框选识词吧。")
            return
        self.review.start()
        self.stack.setCurrentIndex(1)
        self._render_review()

    def _render_review(self) -> None:
        if not self.review.running:
            self._back_to_list()
            return
        card = self.review.card()
        self.review_word.setText(card["word"])
        self.review_phon.setText(card["phonetic"])
        self.review_mean.setText(card["meaning"])
        self.review_mean.setVisible(card["revealed"])
        self.review_tip.setVisible(not card["revealed"])
        self.review_progress.setText(
            f"{card['index']} / {card['total']}　·　"
            f"{card['stageLabel']}　·　{'今天到期' if card['due'] else '提前复习'}")

    def reveal(self) -> None:
        self.review.reveal()
        self._render_review()

    def step(self, delta: int) -> None:
        if not self.review.running:
            return
        self.review.step(delta)
        self._render_review()

    def _grade(self, correct: bool) -> None:
        if not self.review.running:
            return
        self.review.grade(correct)
        self.review.rebuild()
        self._render_review()

    def _back_to_list(self) -> None:
        self.stack.setCurrentIndex(0)
        self.refresh()


class ModeDialog(QDialog):
    """识词模式设置：选考纲、是否跳过虚词、最多挑几个词。"""

    def __init__(self, parent, mode: str, skip_stopwords: bool, limit: int):
        super().__init__(parent)
        self.setWindowTitle("识词设置")
        self.setStyleSheet(QSS)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel("识词设置")
        title.setObjectName("title")
        layout.addWidget(title)

        sub = QLabel("考纲标签来自 ECDICT 的独立标签表，与词典本体解耦。")
        sub.setObjectName("sub")
        layout.addWidget(sub)

        row = QHBoxLayout()
        row.addWidget(QLabel("考纲"))
        self.combo = QComboBox()
        for key in lexicon.MODE_ORDER:
            self.combo.addItem(lexicon.MODE_DISPLAY[key], key)
        index = self.combo.findData(mode)
        self.combo.setCurrentIndex(index if index >= 0 else 1)
        row.addWidget(self.combo, 1)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("最多挑"))
        self.combo_limit = QComboBox()
        # 2026-10-19：档位收成 8 / 16 / 32 / 48（去掉了 4 和 24）。
        # 四档正好是「一批 / 两批 / 四批 / 六批」—— 八条腿是**同时**踩词的
        # 并行度，不是一次能处理多少个词的上限，所以往上只是让队列更长。
        # 档位表只有 `settings_store.MAX_WORDS_CHOICES` 一处来源。
        for n in settings_store.MAX_WORDS_CHOICES:
            self.combo_limit.addItem(f"{n} 个", n)
        want = int(limit)
        index = self.combo_limit.findData(want)
        if index < 0:
            # 老配置里存的是 6 这类历史值：选**最接近**的一档。
            # 写死 `else 2` 的话，用户原来的 6 会被悄悄改成 16。
            index = min(range(self.combo_limit.count()),
                        key=lambda i: abs(self.combo_limit.itemData(i) - want))
        self.combo_limit.setCurrentIndex(index)
        row2.addWidget(self.combo_limit, 1)
        layout.addLayout(row2)

        self.check_skip = QCheckBox("跳过 the / of / because 这类虚词")
        self.check_skip.setChecked(skip_stopwords)
        layout.addWidget(self.check_skip)

        buttons = QHBoxLayout()
        ok = QPushButton("保存")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)
        self.resize(360, 250)
        _enable_button_cursors(self)

    def values(self) -> dict:
        return {
            "mode": self.combo.currentData(),
            "limit": self.combo_limit.currentData(),
            "skip_stopwords": self.check_skip.isChecked(),
        }
