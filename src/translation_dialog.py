"""Editable source and a plain-text English result next to a screen selection."""
import time

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QTextEdit, QVBoxLayout)

from ai.config import AIConfig
from ai.translation import MAX_SOURCE_CHARS, TranslationService
from lexara_theme import ACCENT, DIALOG_QSS, INK, LINE, SURFACE, SURFACE_ALT


def card_geometry(selection: QRect, available: QRect) -> QRect:
    width, height = min(480, available.width()), min(520, available.height())
    x, y = selection.right() + 12, selection.top()
    if x + width > available.right() + 1:
        x = selection.left() - width - 12
    if x < available.left():
        x, y = selection.left(), selection.bottom() + 12
    x = max(available.left(), min(x, available.right() + 1 - width))
    y = max(available.top(), min(y, available.bottom() + 1 - height))
    return QRect(x, y, width, height)


class TranslationDialog(QDialog):
    busyChanged = Signal(bool)

    def __init__(self, settings, parent=None, service=None):
        super().__init__(parent, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("框选中译英 · LEXARA")
        self.setStyleSheet(DIALOG_QSS + f"""
            QPlainTextEdit {{
                border:1px solid {LINE}; border-radius:8px; padding:8px;
                color:{INK}; background:{SURFACE}; font-size:13px;
                selection-background-color:{ACCENT};
            }}
            QPlainTextEdit:focus {{ border-color:{ACCENT}; }}
            QPlainTextEdit#translationResult {{ background:{SURFACE_ALT}; }}
            QPushButton#translate {{ background:{ACCENT}; color:white; border:0; }}
            QPushButton#translate:disabled {{ background:{SURFACE_ALT}; color:#747474; }}
        """)
        self.resize(480, 520)
        self._phase = "idle"
        self._phase_started = time.monotonic()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(100)
        self._elapsed_timer.timeout.connect(self._refresh_status)
        self.service = service or TranslationService(AIConfig(settings), self)
        self.service.changed.connect(self._refresh)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        title = QLabel("中文 → English")
        title.setObjectName("title")
        layout.addWidget(title)
        privacy = QLabel("OCR：本机 RapidOCR · 翻译：已配置的 AI 服务\n仅发送下方原文，不上传截图。")
        privacy.setWordWrap(True)
        privacy.setObjectName("sub")
        layout.addWidget(privacy)
        layout.addWidget(QLabel("中文原文（可修改后重译）"))
        self.source = QPlainTextEdit()
        self.source.setPlaceholderText("识别出的中文会显示在这里，也可以直接输入中文。")
        layout.addWidget(self.source, 1)
        self.counter = QLabel()
        self.counter.setObjectName("sub")
        layout.addWidget(self.counter)
        self.warning = QLabel()
        self.warning.setTextFormat(Qt.PlainText)
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color:#8A6A2B;font-size:11px;")
        self.warning.hide()
        layout.addWidget(self.warning)
        layout.addWidget(QLabel("英文译文"))
        self.result = QPlainTextEdit()
        self.result.setObjectName("translationResult")
        self.result.setReadOnly(True)
        self.result.setPlaceholderText("英文译文会显示在这里")
        layout.addWidget(self.result, 1)
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.retry = QPushButton("翻译")
        self.retry.setObjectName("translate")
        self.copy = QPushButton("复制译文")
        close = QPushButton("关闭")
        buttons.addWidget(self.retry)
        buttons.addWidget(self.copy)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.retry.clicked.connect(lambda: self.service.translate(self.source.toPlainText()))
        self.copy.clicked.connect(self._copy)
        close.clicked.connect(self.close)
        self.source.textChanged.connect(self._edited)
        self._refresh()

    def begin(self, array, selection, min_conf=0.0):
        screen = QGuiApplication.screenAt(selection.center()) or QGuiApplication.primaryScreen()
        if screen:
            self.setGeometry(card_geometry(selection, screen.availableGeometry()))
        self.show()
        self.raise_()
        self.activateWindow()
        self.service.recognize(array, min_conf)

    def _edited(self):
        length = len(self.source.toPlainText().strip())
        self.counter.setText("%d / %d 字符" % (length, MAX_SOURCE_CHARS))
        busy = self.service.state["state"] in ("recognizing", "translating")
        self.retry.setEnabled(not busy and 0 < length <= MAX_SOURCE_CHARS)
        # Never offer an old translation for newly edited source material.
        if not busy and self.source.toPlainText().strip() != self.service.state["source"]:
            self.result.clear()
            self.source.setExtraSelections([])
            self.warning.hide()
            self.copy.setEnabled(False)
            self.status.setText("原文已修改，点击翻译生成新译文。")

    def _refresh(self):
        state = self.service.state
        phase = state["state"]
        if phase != self._phase:
            self._phase, self._phase_started = phase, time.monotonic()
        busy = phase in ("recognizing", "translating")
        self.source.setReadOnly(busy)
        if phase in ("recognizing", "review", "translating", "done", "error"):
            if self.source.toPlainText() != state["source"]:
                self.source.setPlainText(state["source"])
        if self.result.toPlainText() != state["text"]:
            scrollbar = self.result.verticalScrollBar()
            follow, old_position = scrollbar.value() >= scrollbar.maximum() - 2, scrollbar.value()
            self.result.setPlainText(state["text"])
            scrollbar.setValue(scrollbar.maximum() if follow else old_position)
        self.copy.setEnabled(phase == "done" and bool(state["text"]))
        self.retry.setText("确认并翻译" if phase == "review" else
                           "重试" if phase == "error" else "重新翻译" if phase == "done" else "翻译")
        self.warning.setText(state.get("warning", ""))
        self.warning.setVisible(bool(state.get("warning")))
        selections = []
        original = self.source.toPlainText()
        for item in state.get("uncertain", []):
            start = original.find(item["text"])
            if start < 0:
                continue
            selection = QTextEdit.ExtraSelection()
            selection.cursor = QTextCursor(self.source.document())
            # Qt uses UTF-16 positions (an emoji occupies two code units).
            selection.cursor.setPosition(len(original[:start].encode("utf-16-le")) // 2)
            end = start + len(item["text"])
            selection.cursor.setPosition(len(original[:end].encode("utf-16-le")) // 2, QTextCursor.KeepAnchor)
            selection.format = QTextCharFormat()
            selection.format.setBackground(QColor("#FFF0B3"))
            selections.append(selection)
        self.source.setExtraSelections(selections)
        self._edited()
        if busy:
            self._elapsed_timer.start()
        else:
            self._elapsed_timer.stop()
        self._refresh_status()
        self.busyChanged.emit(busy)

    def _refresh_status(self):
        state, phase = self.service.state, self.service.state["state"]
        elapsed = time.monotonic() - self._phase_started
        translating = ("正在生成英文 · 已显示 %d 字符 · %.1f 秒" % (len(state["text"]), elapsed)
                       if state["text"] else "正在等待译文 · %.1f 秒" % elapsed)
        self.status.setText({
            "recognizing": "正在本机识别中文 · %.1f 秒" % elapsed,
            "review": "核对黄色文字后，点击「确认并翻译」。",
            "translating": translating + " · 关闭可取消",
            "done": "翻译完成 · 识别 %.1f 秒 · 翻译 %.1f 秒" % (
                state.get("ocr_seconds", 0), state.get("translation_seconds", 0)),
        }.get(phase, state["error"]))

    def _copy(self):
        QApplication.clipboard().setText(self.result.toPlainText())
        self.status.setText("译文已复制。")

    def closeEvent(self, event):
        self.service.cancel()
        super().closeEvent(event)

    def reject(self):
        self.service.cancel()
        super().reject()
