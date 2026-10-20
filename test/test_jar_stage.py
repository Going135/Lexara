"""展示区（JarView）的图层不透明度 —— 任务书 §2.4。

背景：2026-10-18 用户反馈「说好 50% 透明度呢」。根因是 `JarItem.paint()`
调 `QWidget.render()` 时用了默认 flags（含 `DrawWindowBackground`），Qt 先把
整块区域用调色板 Window 色**不透明地**填一遍，`JarView.paintEvent()` 里那层
`QColor(255, 255, 255, 128)` 就被压在下面 —— 界面上看到的是一块死白的板子。

这个测试直接走 `JarItem.draw_jar()`（生产代码里唯一的绘制点），把结果画进
透明 QImage 再逐像素量 alpha，确保：

1. 底板内部 alpha = 128（50%），不是 255；
2. RGB 仍是纯白（不是被调色板染成 249,249,249）；
3. 圆角**外面**完全透明（说明底板是圆角矩形，不是铺满整块的矩形）；
4. 蜘蛛本身仍是不透明的（这一层不该被连带削弱）。

不许把 alpha 断言写成「> 0」，那样改回不透明也照样通过。
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

# Qt Quick Controls 样式必须在 QApplication 之前指定（项目已知坑）
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QPoint, QSize, Qt          # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter   # noqa: E402
from PySide6.QtWidgets import QApplication           # noqa: E402

_app = QApplication.instance() or QApplication([])

import launcher_qml                                  # noqa: E402
import launcher_window as LW                         # noqa: E402

WIDTH, HEIGHT = 400, 200        # JarView 内部按 2:1 展示区设计


def render_stage() -> QImage:
    """按 `JarItem.paint()` 的真实路径渲染一帧，透明底。"""
    jar = LW.JarView()
    jar.resize(WIDTH, HEIGHT)
    jar.reset()

    image = QImage(QSize(WIDTH, HEIGHT), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    try:
        launcher_qml.JarItem.draw_jar(painter, jar, WIDTH, HEIGHT)
    finally:
        painter.end()
    return image


class StageOpacityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.image = render_stage()

    def test_plate_is_half_transparent(self):
        """底板内部 alpha=128：这就是「白色 50%」。"""
        color = self.image.pixelColor(40, HEIGHT // 2)
        self.assertEqual(color.alpha(), 128,
                         "底板必须是不透明度 50%%（alpha 128），实际 %d"
                         % color.alpha())
        self.assertEqual(color.red(), 255)
        self.assertEqual(color.green(), 255)
        self.assertEqual(color.blue(), 255)

    def test_plate_is_not_opaque_anywhere(self):
        """整块底板都没有不透明填充（防止 render() flags 被改回去）。"""
        opaque = 0
        for x in range(10, WIDTH - 10, 7):
            for y in range(10, HEIGHT - 10, 7):
                if self.image.pixelColor(x, y).alpha() == 255:
                    opaque += 1
        # 蜘蛛本体、地面阴影、描边都是不透明的，但占比很小；
        # 一旦整块被填成 249,249,249,255 这个数字会跳到上百。
        self.assertLess(opaque, 200,
                        "底板出现大面积不透明像素（%d 个采样点），"
                        "很可能是 QWidget.render() 又把 DrawWindowBackground "
                        "带回来了" % opaque)

    def test_corners_are_transparent(self):
        """圆角矩形之外必须完全透明，否则卡片渐变透不过来。"""
        self.assertEqual(self.image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(self.image.pixelColor(WIDTH - 1, 0).alpha(), 0)
        self.assertEqual(self.image.pixelColor(0, HEIGHT - 1).alpha(), 0)
        self.assertEqual(self.image.pixelColor(WIDTH - 1, HEIGHT - 1).alpha(), 0)

    def test_spider_layer_stays_opaque(self):
        """蜘蛛本体不受底板影响：必须有接近实心的像素（alpha ≥ 250）。

        蜘蛛每帧位置不同（步态在走），所以不能写死坐标 —— 这里统计的是
        「有没有 alpha ≥ 250 的像素」，底板只有 128，命中的只可能是蜘蛛
        （细腿经过抗锯齿会低于 250，所以取 ≥250 而不是 ==255）。
        """
        solid = 0
        for x in range(WIDTH):
            for y in range(HEIGHT):
                if self.image.pixelColor(x, y).alpha() >= 250:
                    solid += 1
        self.assertGreater(
            solid, 30,
            "只找到 %d 个实心像素：蜘蛛本体被连带画成半透明了"
            "（底板 alpha 128 不该影响蜘蛛层）" % solid)


class StageRenderFlagTest(unittest.TestCase):
    """守住根因：默认 flags 会把整块填成不透明，这就是当初的 bug。"""

    def test_default_render_flags_fill_opaque(self):
        jar = LW.JarView()
        jar.resize(WIDTH, HEIGHT)
        jar.reset()
        image = QImage(QSize(WIDTH, HEIGHT), QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        from PySide6.QtGui import QRegion
        try:
            jar.render(painter, QPoint(0, 0), QRegion(0, 0, WIDTH, HEIGHT))
        finally:
            painter.end()
        # 默认 flags 下这一格是不透明的 —— 所以生产代码必须显式传 DrawChildren
        self.assertEqual(image.pixelColor(40, HEIGHT // 2).alpha(), 255)


if __name__ == "__main__":
    unittest.main(verbosity=2)
