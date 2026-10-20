# -*- coding: utf-8 -*-
"""LEXARA UI design system.

视觉规则只负责表现，不承载业务状态：
- warm white / white / charcoal 为基础
- 单一 cobalt accent 用于选中、焦点、进度与识别
- 不使用彩虹渐变、玻璃渐变或大面积阴影
- 8px spacing grid；8 / 12 / 16px radius
- 几何切角只作为少量识别细节
"""

BG = "#F5F5F2"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F0F0ED"
SURFACE_HOVER = "#F7F7F4"
INK = "#151515"
TEXT = "#2B2B2B"
MUTED = "#747474"
SUBTLE = "#9A9A96"
LINE = "#E4E4DF"
LINE_STRONG = "#CFCFCA"
ACCENT = "#2F6BFF"
ACCENT_SOFT = "#EEF3FF"
SUCCESS = "#4F765F"
WARNING = "#8A6A2B"
DANGER = "#C44D47"

FONT_FAMILY = '"Inter", "Microsoft YaHei UI", "Segoe UI"'

APP_QSS = f"""
* {{
  font-family:{FONT_FAMILY};
}}
QToolTip {{
  background:{INK};
  color:#fff;
  border:0;
  padding:6px 9px;
  border-radius:6px;
}}
QPushButton {{
  min-height:34px;
  padding:0 13px;
  border:1px solid {LINE};
  border-radius:9px;
  background:{SURFACE};
  color:{TEXT};
  font-size:12px;
}}
QPushButton:hover {{
  background:{SURFACE_HOVER};
  border-color:{LINE_STRONG};
}}
QPushButton:pressed {{
  background:#EAEAE6;
}}
QPushButton:disabled {{
  background:{SURFACE_ALT};
  color:{SUBTLE};
  border-color:{LINE};
}}
#winTitle {{
  color:{INK};
  font-size:14px;
  font-weight:700;
  letter-spacing:.15px;
}}
#winTitleSub {{
  color:{MUTED};
  font-size:11px;
}}
#statusChip {{
  color:{MUTED};
  font-size:10.5px;
  background:transparent;
  border:0;
  padding:0;
}}
#winBtn, #closeBtn, #gearBtn {{
  min-width:30px;
  max-width:30px;
  min-height:30px;
  max-height:30px;
  padding:0;
  border:0;
  border-radius:8px;
  background:transparent;
  color:{MUTED};
}}
#winBtn:hover, #gearBtn:hover {{
  background:{SURFACE_ALT};
  color:{INK};
}}
#closeBtn:hover {{
  background:#F3E9E7;
  color:{DANGER};
}}
#gearBtn[open="true"] {{
  background:{ACCENT_SOFT};
  color:{ACCENT};
}}
#panelHead {{
  color:{INK};
  font-size:13px;
  font-weight:650;
  letter-spacing:.1px;
}}
#panelNote {{
  color:{MUTED};
  font-size:10.5px;
}}
#sectionTitle {{
  color:{INK};
  font-size:13px;
  font-weight:650;
}}
#wordsCount {{
  color:{MUTED};
  font-size:10.5px;
}}
QScrollArea#panelScroll {{
  border:0;
  background:transparent;
}}
#segBtn {{
  min-height:30px;
  padding:0 10px;
  border:1px solid {LINE};
  border-radius:8px;
  background:{SURFACE};
  color:{TEXT};
  font-size:11px;
}}
#segBtn:hover {{
  background:{SURFACE_HOVER};
  border-color:{LINE_STRONG};
}}
#segBtn:checked {{
  background:{ACCENT_SOFT};
  border-color:{ACCENT};
  color:{ACCENT};
  font-weight:650;
}}
#check {{
  color:{TEXT};
  font-size:11.5px;
  spacing:7px;
  padding:0 2px;
  border:0;
  background:transparent;
}}
#check:hover {{
  color:{INK};
}}
#check::indicator {{
  width:16px;
  height:16px;
  border-radius:4px;
  border:1px solid {LINE_STRONG};
  background:{SURFACE};
}}
#check::indicator:hover {{
  border-color:{INK};
}}
#check::indicator:checked {{
  border-color:{ACCENT};
  background:{ACCENT};
}}
QSlider::groove:horizontal {{
  height:3px;
  border-radius:2px;
  background:{LINE};
}}
QSlider::sub-page:horizontal {{
  background:{ACCENT};
  border-radius:2px;
}}
QSlider::add-page:horizontal {{
  background:{LINE};
  border-radius:2px;
}}
QSlider::handle:horizontal {{
  width:16px;
  height:16px;
  margin:-6px 0;
  border-radius:8px;
  background:{SURFACE};
  border:1px solid {ACCENT};
}}
QSlider::handle:horizontal:hover {{
  background:{ACCENT_SOFT};
}}
#scaleOut {{
  min-width:42px;
  padding:3px 6px;
  color:{INK};
  font-size:11px;
  font-weight:650;
  border:0;
  background:transparent;
}}
#dataLine {{
  color:{MUTED};
  font-size:10.5px;
  background:{SURFACE_ALT};
  border:0;
  border-radius:8px;
  padding:7px 10px;
}}
#wordChip {{
  min-height:44px;
  padding:0;
  border:1px solid {LINE};
  border-radius:9px;
  background:{SURFACE};
  color:{TEXT};
}}
#wordChip:hover {{
  background:{SURFACE_HOVER};
  border-color:{LINE_STRONG};
}}
#wordEmpty {{
  color:{MUTED};
  font-size:11px;
  border:1px dashed {LINE_STRONG};
  border-radius:8px;
  padding:10px;
  background:{SURFACE_ALT};
}}
#footRow {{
  border-top:1px solid #ECECE8;
  background:{SURFACE};
}}
#firstUse {{
  color:{MUTED};
  font-size:11px;
}}
#deployBtn {{
  min-width:214px;
  max-width:260px;
  min-height:54px;
  border-radius:10px;
  color:#fff;
  background:{INK};
  border:1px solid {INK};
  font-size:18px;
  font-weight:700;
  letter-spacing:4px;
  padding:0 22px;
}}
#deployBtn:hover {{
  background:#2A2A2A;
  border-color:#2A2A2A;
}}
#deployBtn:pressed {{
  background:#000;
}}
#deployBtn:disabled {{
  background:#A8A8A2;
  border-color:#A8A8A2;
  color:#fff;
}}
#deployBtn[mode="recall"] {{
  background:{SURFACE};
  color:{INK};
  border-color:{INK};
}}
#deployBtn[mode="recall"]:hover {{
  background:{SURFACE_ALT};
}}
#deployBtn[mode="recall"]:pressed {{
  background:#EAEAE6;
}}
#deployBtn[mode="recall"]:disabled {{
  background:{SURFACE_ALT};
  color:{SUBTLE};
  border-color:{LINE};
}}
#sheet {{
  background:{SURFACE};
  border:1px solid {LINE};
  border-radius:14px;
}}
#sheetTitle {{
  color:{INK};
  font-size:15px;
  font-weight:700;
}}
#sheetNote, #sheetLabel {{
  color:{MUTED};
  font-size:10.5px;
}}
"""

DIALOG_QSS = f"""
* {{
  font-family:{FONT_FAMILY};
}}
QDialog {{
  background:{SURFACE};
  color:{TEXT};
}}
QLabel {{
  color:{TEXT};
  font-size:12.5px;
}}
QLabel#title {{
  color:{INK};
  font-size:18px;
  font-weight:700;
}}
QLabel#sub {{
  color:{MUTED};
  font-size:11px;
}}
QLabel#analysis {{
  color:{ACCENT};
  background:{ACCENT_SOFT};
  border:1px solid #C9D8FF;
  border-radius:8px;
  padding:7px 10px;
  font-size:11px;
  font-weight:650;
}}
QLabel#word {{
  color:{INK};
  font-size:26px;
  font-weight:700;
  letter-spacing:.2px;
}}
QLabel#phon {{
  color:{MUTED};
  font-size:12px;
}}
QLabel#mean {{
  color:{TEXT};
  font-size:13.5px;
}}
QLabel#badge {{
  color:{ACCENT};
  background:{ACCENT_SOFT};
  border:1px solid #C9D8FF;
  border-radius:6px;
  padding:2px 7px;
  font-size:10px;
  font-weight:650;
}}
QLabel#off {{
  color:{WARNING};
  background:#F5F1E7;
  border:1px solid #E5DCC5;
  border-radius:6px;
  padding:2px 7px;
  font-size:10px;
}}
QFrame#card {{
  background:{SURFACE};
  border:1px solid {LINE};
  border-radius:12px;
}}
QFrame#cardOn {{
  background:{ACCENT_SOFT};
  border:1px solid #BFD0FF;
  border-radius:12px;
}}
QFrame#card:hover {{
  background:{SURFACE_HOVER};
  border-color:{LINE_STRONG};
}}
QPushButton {{
  min-height:34px;
  background:{SURFACE};
  border:1px solid {LINE};
  border-radius:9px;
  padding:0 14px;
  color:{TEXT};
  font-size:12px;
}}
QPushButton:hover {{
  background:{SURFACE_ALT};
  border-color:{LINE_STRONG};
}}
QPushButton:pressed {{
  background:#EAEAE6;
}}
QPushButton#primary {{
  background:{INK};
  border:1px solid {INK};
  color:#fff;
  font-weight:650;
}}
QPushButton#primary:hover {{
  background:#2A2A2A;
}}
QPushButton#star, QPushButton#starOn {{
  min-width:36px;
  max-width:36px;
  min-height:36px;
  max-height:36px;
  padding:7px;
  border-radius:8px;
  background:{SURFACE};
  border:1px solid {LINE};
}}
QPushButton#starOn {{
  background:{ACCENT_SOFT};
  border-color:#BFD0FF;
}}
QLineEdit, QComboBox {{
  min-height:34px;
  background:{SURFACE};
  border:1px solid {LINE};
  border-radius:8px;
  padding:0 10px;
  color:{INK};
  font-size:12px;
}}
QLineEdit:hover, QComboBox:hover {{
  border-color:{LINE_STRONG};
}}
QLineEdit:focus, QComboBox:focus {{
  border-color:{ACCENT};
}}
QComboBox::drop-down {{
  border:0;
  width:24px;
}}
QComboBox QAbstractItemView {{
  background:{SURFACE};
  color:{TEXT};
  selection-background-color:{ACCENT_SOFT};
  selection-color:{ACCENT};
  border:1px solid {LINE};
}}
QScrollArea {{
  border:0;
  background:transparent;
}}
QScrollBar:vertical {{
  background:transparent;
  width:6px;
}}
QScrollBar::handle:vertical {{
  background:#D0D0CB;
  border-radius:3px;
  min-height:28px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
  height:0;
}}
QListWidget {{
  background:{SURFACE};
  border:1px solid {LINE};
  border-radius:10px;
  color:{TEXT};
  font-size:12px;
}}
QListWidget::item {{
  padding:10px 10px;
  border-bottom:1px solid #EEEEEA;
}}
QListWidget::item:hover {{
  background:{SURFACE_HOVER};
}}
QListWidget::item:selected {{
  background:{ACCENT_SOFT};
  color:{ACCENT};
}}
QCheckBox {{
  color:{TEXT};
  font-size:12px;
  spacing:7px;
}}
QCheckBox::indicator {{
  width:16px;
  height:16px;
  border-radius:4px;
  border:1px solid {LINE_STRONG};
  background:{SURFACE};
}}
QCheckBox::indicator:checked {{
  border-color:{ACCENT};
  background:{ACCENT};
}}
#sidebar {{
  background:#E9EBCB;
  border:1px solid #DCE6D5;
  border-radius:16px;
}}
#logo {{ color:{INK}; font-size:22px; font-weight:800; letter-spacing:2px; }}
#sideSub {{ color:{MUTED}; font-size:10px; }}
#reviewCard {{ background:#FFFFFF; border:1px solid #E1E5ED; border-radius:12px; }}
#sideTitle {{ color:{INK}; font-size:12px; font-weight:700; }}
#sideMetric {{ color:{MUTED}; font-size:11px; padding-top:3px; }}
#sideAction {{ min-height:34px; text-align:left; border:0; background:transparent;
  color:{TEXT}; padding:0 8px; border-radius:8px; }}
#sideAction:hover {{ background:#FFFFFF; color:{ACCENT}; }}
#mainContent {{ background:#FFFFFF; border:1px solid #E5E5E0; border-radius:18px; }}
#pageTitle {{ color:{INK}; font-size:19px; font-weight:750; }}
#pageStatus {{ color:{MUTED}; font-size:11px; padding:5px 11px; border:1px solid {LINE};
  border-radius:14px; background:#FFFFFF; }}
#heroCard {{ background:#FFFFFF; border:1px solid {LINE}; border-radius:16px; }}
#heroArt {{ background:#FFFFFF; border:0; }}
#cardTitle {{ color:{MUTED}; font-size:11px; padding-left:4px; }}
#activityCard {{ background:transparent; }}
#inputCard {{ background:#FFFFFF; border:1px solid {LINE}; border-radius:13px; }}
#compactControl {{ min-height:32px; max-height:32px; padding:0 10px; font-size:11px; }}
#aiInput {{ border:0; background:transparent; min-height:32px; }}
#sendButton {{ min-height:32px; background:{ACCENT_SOFT}; color:{ACCENT};
  border:1px solid #C9D8FF; border-radius:8px; font-weight:700; }}
#sendButton:hover {{ background:#DCE7FF; }}
#shellDeploy {{ min-height:50px; min-width:122px; padding:0 24px; border-radius:13px;
  background:{INK}; color:#FFFFFF; border:1px solid {INK}; font-size:15px; font-weight:750; }}
#shellDeploy:hover {{ background:#303030; }}
#shellDeploy:disabled {{ background:#A8A8A2; border-color:#A8A8A2; }}
#calendarTitle {{ color:{INK}; font-size:12px; font-weight:700; }}
#calendarHint {{ color:{MUTED}; font-size:10px; }}
"""
