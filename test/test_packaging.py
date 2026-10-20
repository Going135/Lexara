# -*- coding: utf-8 -*-
"""打包瘦身的守卫测试。

背景（2026-10-18）：产物体积 412MB，其中 OpenCV 占 112MB。查下来
**cv2 本身不能删** —— `rapidocr_onnxruntime` 有 6 个文件直接 `cv2.resize` /
`warpAffine` / `cvtColor`，删掉 OCR 就废了。但 cv2 里躺着一个 29MB 的
`opencv_videoio_ffmpeg500_64.dll`，那是**视频**编解码插件，只服务
`VideoCapture` / `VideoWriter`，本项目连读图都走 Qt 的 QImage。

所以规则是「留 cv2、去掉它的视频插件」。这两件事都很容易被人手滑改回去：

* 有人为了瘦身把 `cv2` 整个加进 spec 的 `excludes`  → OCR 静默失效
* 有人为了读个视频/摄像头把 `VideoCapture` 引进来   → 打包后运行时缺 dll

这个测试把两条都钉住。
"""

import os
import re
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

SPECS = ("Lexara.spec", "LexaraDebug.spec", "LexaraFixed.spec",
         "LexaraPortable.spec", "LexaraPortableDebug.spec")

#: 剔除规则必须命中这个片段（OpenCV 的视频编解码插件）。
DROP_KEY = "opencv_videoio_ffmpeg"


def _read(rel_path):
    with open(os.path.join(BASE, rel_path), encoding="utf-8", errors="ignore") as handle:
        return handle.read()


def _py_files(*roots):
    """遍历给定目录下的 .py（跳过 __pycache__）。"""
    for root in roots:
        for dirpath, _dirs, names in os.walk(os.path.join(BASE, root)):
            if "__pycache__" in dirpath:
                continue
            for name in names:
                if name.endswith(".py"):
                    yield os.path.join(dirpath, name)


class SpecDropCase(unittest.TestCase):
    """五个 spec 都要剔除 ffmpeg 插件，且**不能**顺手把 cv2 排除掉。"""

    def test_all_specs_drop_ffmpeg(self):
        for spec in SPECS:
            with self.subTest(spec=spec):
                text = _read(spec)
                self.assertIn("_DROP_BINARIES", text,
                              "%s 缺少剔除规则" % spec)
                self.assertIn(DROP_KEY, text,
                              "%s 的剔除规则没指向 %s" % (spec, DROP_KEY))
                # 规则必须真的作用在 a.binaries 上（只写注释不算）
                self.assertRegex(text, r"a\.binaries\s*=\s*\[",
                                 "%s 的规则没有作用到 a.binaries" % spec)

    def test_cv2_is_not_excluded(self):
        """cv2 是 RapidOCR 的硬依赖，任何 spec 都不许 exclude 它。"""
        for spec in SPECS:
            with self.subTest(spec=spec):
                text = _read(spec)
                match = re.search(r"excludes=\[(.*?)\]", text, re.S)
                self.assertIsNotNone(match, "%s 找不到 excludes 列表" % spec)
                self.assertNotIn("'cv2'", match.group(1),
                                 "%s 把 cv2 排除了 —— OCR 会静默失效" % spec)
                self.assertNotIn('"cv2"', match.group(1),
                                 "%s 把 cv2 排除了 —— OCR 会静默失效" % spec)


class NoVideoApiCase(unittest.TestCase):
    """剔除 ffmpeg 插件的前提：全仓（含 rapidocr）不用视频 API。"""

    def test_project_never_uses_video_io(self):
        # 只认「调用」（带括号），不认注释/字符串里提到的名字 ——
        # 否则体检工具自己的说明文字就会被判成违规。
        pattern = re.compile(r"\b(VideoCapture|VideoWriter)\s*\(|cv2\.imshow\s*\(")
        offenders = []
        for path in _py_files("src", "tools"):
            text = open(path, encoding="utf-8", errors="ignore").read()
            if pattern.search(text):
                offenders.append(os.path.relpath(path, BASE))
        self.assertEqual(offenders, [],
                         "这些文件开始用视频 API 了，spec 里的 ffmpeg 剔除要先复核：%s"
                         % offenders)

    def test_rapidocr_only_uses_image_api(self):
        """顺带确认 rapidocr 用的是 imread/imwrite（image codecs，内置在 cv2.pyd），
        而不是 VideoCapture —— 这才让「删视频插件」是安全的。"""
        try:
            import rapidocr_onnxruntime
        except Exception:                                   # noqa: BLE001
            self.skipTest("未安装 rapidocr_onnxruntime")
        root = os.path.dirname(rapidocr_onnxruntime.__file__)
        for dirpath, _dirs, names in os.walk(root):
            for name in names:
                if not name.endswith(".py"):
                    continue
                text = open(os.path.join(dirpath, name),
                            encoding="utf-8", errors="ignore").read()
                self.assertNotRegex(text, r"VideoCapture\s*\(",
                                    "%s 调用了 VideoCapture" % name)


class KnownBigFilesCase(unittest.TestCase):
    """把「哪些大块是死重、哪些必须留」记录下来，防止有人乱删。"""

    def test_audit_tool_exists_and_lists_openblas(self):
        text = _read(os.path.join("tools", "package_size_audit.py"))
        self.assertIn("opencv_videoio_ffmpeg", text)
        # numpy.libs 是 OpenBLAS，删了 numpy 就导入不了 —— 体检工具里必须标 keep
        self.assertIn("numpy.libs", text)
        self.assertRegex(text, r'"(numpy\.libs|onnxruntime|icudt78\.dll)", "keep"')


if __name__ == "__main__":
    unittest.main(verbosity=2)
