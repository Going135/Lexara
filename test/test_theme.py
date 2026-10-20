# -*- coding: utf-8 -*-
"""主题令牌体系（外部调参）—— 任务书 §2 视觉部分的可维护性保障。

这套东西最容易坏的地方不是「颜色不好看」，而是**悄悄坏**：

1. 有人往 QML 里又写了一个 `"#FFFFFF"`，从此这个颜色不受主题控制，
   外部调参改不动它 —— 界面上会留一块「改不掉的白」；
2. 有人打错键名（`tv["btn.primaryBg"]` 写成 `tv["btn.primryBg"]`），QML 拿到
   undefined，那个控件直接透明，而日志里只有一条不显眼的警告；
3. 有人改主题文件时写坏 JSON，启动器打不开 —— 这是最不可接受的；
4. 写回时把 `@base.accent` 这样的引用**解析成具体色**存回去，从此「改强调色
   按钮不跟了」，而且没人会发现。

所以这里的断言是围绕这四件事写的，不是围绕「默认色等于 #1F1F1F」。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

import ui_theme                                              # noqa: E402

QML_MAIN = os.path.join(BASE, "src", "qml", "Main.qml")
TOOL = os.path.join(BASE, "tools", "theme_tool.py")
PYTHON = sys.executable


def _temp_theme() -> str:
    handle, path = tempfile.mkstemp(prefix="lexara_theme_", suffix=".json")
    os.close(handle)
    os.unlink(path)                       # 让被测代码自己决定「文件不存在」怎么办
    return path


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class TokenTableTest(unittest.TestCase):
    """令牌表本身要自洽 —— 编错了会在运行期变成一片透明的控件。"""

    def test_keys_unique_and_prefixed(self):
        # 分组是「人看的分区」，键前缀是「机器看的命名」；两者大体一一对应，
        # 但外壳这一组同时管外壳渐变、主卡片渐变和展示区（都是同一条视觉链），
        # 所以前缀允许多个。
        prefixes = {
            "base": ("base.",),
            "shell": ("shell.", "hero.", "stage."),
            "shadow": ("shadow.",),
            "btn": ("btn.",),
            "heat": ("heat.",),
        }
        seen = set()
        for key, token in ui_theme.SPEC.items():
            self.assertNotIn(key, seen, "重复的令牌键：%s" % key)
            seen.add(key)
            allowed = prefixes.get(token["group"], (token["group"] + ".",))
            self.assertTrue(key.startswith(allowed),
                            "%s 的前缀应该属于分组 %s（%s）" % (key, token["group"], allowed))
            self.assertTrue(token["label"], "%s 缺中文名（命令行靠它显示）" % key)
            self.assertTrue(token["desc"], "%s 缺说明（调参页靠它解释）" % key)

    def test_defaults_are_valid(self):
        """每个默认值都必须能通过自己的校验（含 @引用 指向存在的键）。"""
        for key, token in ui_theme.SPEC.items():
            value, error = ui_theme.coerce(key, token["default"], strict=True)
            self.assertIsNone(error, "%s 的默认值不合法：%s" % (key, error))
            self.assertEqual(value, token["default"])

    def test_numeric_tokens_have_ranges(self):
        for key, token in ui_theme.SPEC.items():
            if token["kind"] in ("int", "number"):
                ui = token.get("ui") or {}
                self.assertIn("min", ui, "%s 缺滑杆下限（调参页会画错）" % key)
                self.assertIn("max", ui, "%s 缺滑杆上限" % key)
                self.assertLess(ui["min"], ui["max"], "%s 的范围反了" % key)

    def test_default_resolved_has_no_refs(self):
        for key, value in ui_theme.DEFAULT_RESOLVED.items():
            self.assertFalse(isinstance(value, str) and value.startswith("@"),
                             "%s 解析后还是引用：%s" % (key, value))


class RefTest(unittest.TestCase):
    """`@其它键` 是这套体系的关键：改一处、跟一串，但又能单独覆盖。"""

    def test_follow(self):
        # 用 merge（而不是裸 resolve_refs）：真实链路是「默认值 + 文件覆盖」，
        # 只传一个键时其余键根本不在字典里，跟不了。
        values, _ = ui_theme.merge({"base.accent": "#E04B3A"})
        self.assertEqual(values["btn.primaryBg"], "#E04B3A",
                         "按钮默认应该跟着强调色走")

    def test_override_breaks_follow(self):
        values = ui_theme.resolve_refs({"base.accent": "#E04B3A",
                                        "btn.primaryBg": "#00FF00"})
        self.assertEqual(values["btn.primaryBg"], "#00FF00")
        self.assertEqual(values["base.accent"], "#E04B3A")

    def test_cycle_falls_back_to_default(self):
        values = ui_theme.resolve_refs({"btn.primaryBg": "@btn.primaryBg"})
        self.assertEqual(values["btn.primaryBg"],
                         ui_theme.DEFAULT_RESOLVED["btn.primaryBg"],
                         "自引用要退回默认色，不能把 '@btn.primaryBg' 当颜色用")

    def test_dangling_ref_falls_back(self):
        values = ui_theme.resolve_refs({"btn.primaryBg": "@nope.nothing"})
        self.assertEqual(values["btn.primaryBg"],
                         ui_theme.DEFAULT_RESOLVED["btn.primaryBg"])


class CoerceTest(unittest.TestCase):
    def test_rejects_bad_color(self):
        for bad in ("red", "", "#12", "#GGGGGG", 123):
            _, error = ui_theme.coerce("base.ink", bad, strict=True)
            self.assertIsNotNone(error, "%r 不该被当成颜色接受" % (bad,))

    def test_accepts_three_forms(self):
        for good in ("#fff", "#FFFFFF", "#80FFFFFF"):
            value, error = ui_theme.coerce("base.ink", good, strict=True)
            self.assertIsNone(error, "%s 应该合法" % good)
            self.assertEqual(value, good)

    def test_range_guard(self):
        _, error = ui_theme.coerce("shadow.strength", "45", strict=True)
        self.assertIsNotNone(error, "45 倍的阴影浓度必须被拦住（少写小数点的典型误输入）")
        value, error = ui_theme.coerce("shadow.strength", "0.08", strict=True)
        self.assertIsNone(error)
        self.assertAlmostEqual(value, 0.08)

    def test_unknown_key(self):
        _, error = ui_theme.coerce("btn.nope", "#FFF", strict=True)
        self.assertIn("未知令牌", error)


class FileTest(unittest.TestCase):
    def setUp(self):
        self.path = _temp_theme()

    def tearDown(self):
        for suffix in ("", ".tmp"):
            if os.path.exists(self.path + suffix):
                os.unlink(self.path + suffix)

    def test_roundtrip_keeps_refs(self):
        """写回时必须保留 `@` 写法，不能固化成具体色。"""
        ui_theme.write_file(self.path, dict(ui_theme.DEFAULT_VALUES))
        raw, _ = ui_theme.read_raw(self.path)
        self.assertEqual(raw["btn.primaryBg"], "@base.accent")

    def test_flatten_unflatten(self):
        data = {"base": {"ink": "#111111"}, "btn": {"primaryBg": "@base.accent"}}
        flat = ui_theme.flatten(data)
        self.assertEqual(flat["btn.primaryBg"], "@base.accent")
        self.assertEqual(ui_theme.unflatten(flat)["base"]["ink"], "#111111")

    def test_broken_json_falls_back(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{ 这不是 json")
        values, problems = ui_theme.read_file(self.path)
        self.assertTrue(problems, "读坏了必须有话说，不能默默用默认值")
        self.assertEqual(values["base.ink"], ui_theme.DEFAULT_RESOLVED["base.ink"],
                         "文件写坏时仍要能起界面")

    def test_unknown_key_is_reported_not_fatal(self):
        ui_theme.write_file(self.path, dict(ui_theme.DEFAULT_VALUES))
        data = _read_json(self.path)
        data["btn"]["primryBg"] = "#FF0000"        # 故意拼错
        _write_json(self.path, data)
        values, problems = ui_theme.read_file(self.path)
        self.assertTrue(any("primryBg" in item for item in problems))
        self.assertIn("btn.primaryBg", values)

    def test_write_is_atomic(self):
        """不允许出现「启动器读到半个 JSON」：写的是 .tmp 再 replace。"""
        ui_theme.write_file(self.path, dict(ui_theme.DEFAULT_VALUES))
        self.assertTrue(os.path.exists(self.path))
        self.assertFalse(os.path.exists(self.path + ".tmp"),
                         "原子写不该留下 .tmp")


class StoreTest(unittest.TestCase):
    """热重载：文件一变，QML 那边的值必须跟着变（不用重启）。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.path = _temp_theme()
        self.store = ui_theme.ThemeStore(self.path, watch=True)
        ui_theme.set_active(self.store)

    def tearDown(self):
        ui_theme.set_active(None)
        self.store.deleteLater()
        for suffix in ("", ".tmp"):
            if os.path.exists(self.path + suffix):
                os.unlink(self.path + suffix)

    def _wait(self, predicate, timeout=2.5):
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        deadline.start(int(timeout * 1000))
        tick = QTimer()
        tick.setInterval(40)

        def _check():
            if predicate():
                loop.quit()

        tick.timeout.connect(_check)
        tick.start()
        loop.exec()
        tick.stop()

    def test_creates_file(self):
        self.assertTrue(os.path.exists(self.path), "第一次启动要落一份可改的默认文件")

    def test_reload_on_write(self):
        self.assertEqual(self.store.v["btn.primaryBg"], "#2F6BFF")
        data = _read_json(self.path)
        data["base"]["accent"] = "#E04B3A"
        _write_json(self.path, data)
        self._wait(lambda: self.store.v["btn.primaryBg"] == "#E04B3A")
        self.assertEqual(self.store.v["btn.primaryBg"], "#E04B3A",
                         "改强调色后按钮应该跟着变（这验证了引用 + 热重载同时生效）")
        self.assertEqual(self.store.reloads, 1)

    def test_reload_twice(self):
        """第二次改也必须生效 —— 原子替换会让文件监听失效，这里守住重挂逻辑。"""
        for index, color in enumerate(("#E04B3A", "#11AA33"), start=1):
            data = _read_json(self.path)
            data["btn"]["primaryBg"] = color
            _write_json(self.path, data)
            self._wait(lambda: self.store.reloads >= index)
        self.assertEqual(self.store.v["btn.primaryBg"], "#11AA33")
        self.assertEqual(self.store.reloads, 2)


class QmlBindingTest(unittest.TestCase):
    """QML 侧的两个「静默坏」：写死颜色、写错键名。"""

    def setUp(self):
        with open(QML_MAIN, encoding="utf-8") as handle:
            self.source = handle.read()

    def test_no_hardcoded_colors_left(self):
        literals = set(re.findall(r'"#[0-9A-Fa-f]{3,8}"', self.source))
        # Canvas 里那两处是绘制指令，不是界面配色：
        #   1) rgbaOf 的兜底色；2) destination-out 擦洞用的纯黑填充
        self.assertEqual(literals, {'"#000000"'},
                         "Main.qml 里还有写死的颜色 %s —— 它们不受主题控制，"
                         "外部调参改不动" % (literals - {'"#000000"'}))

    def test_every_token_exists(self):
        used = set(re.findall(r'tv\["([^"]+)"\]', self.source))
        self.assertGreater(len(used), 50, "令牌绑定数量不对劲，可能被误删了")
        missing = sorted(key for key in used if key not in ui_theme.SPEC)
        self.assertEqual(missing, [], "QML 引用了不存在的令牌（拼错会变成透明控件）")

    def test_tokens_are_actually_used(self):
        """反向检查：令牌表里不能有一堆「写了但界面没用」的僵尸键。

        `stage.*` 是例外：展示区那层白纱和描边在 `JarView.paintEvent()` 里用
        Qt 画笔画的（不是 QML 控件），所以它们被 Python 消费，不出现 `tv[...]`。
        """
        python_painted = {"stage.overlayAlpha", "stage.border"}
        used = set(re.findall(r'tv\["([^"]+)"\]', self.source))
        unused = [key for key in ui_theme.SPEC
                  if key not in used and key not in python_painted]
        self.assertEqual(unused, [],
                         "这些令牌没被 QML 用到：%s（要么接上，要么删掉）" % unused)


class CliTest(unittest.TestCase):
    """命令行是「外部调参」的主入口，端到端跑一遍。"""

    def setUp(self):
        self.path = _temp_theme()
        self.env = dict(os.environ,
                        LEXARA_THEME=self.path,
                        PYTHONIOENCODING="utf-8",
                        NO_COLOR="1")

    def tearDown(self):
        for suffix in ("", ".tmp"):
            if os.path.exists(self.path + suffix):
                os.unlink(self.path + suffix)

    def _run(self, *args):
        return subprocess.run([PYTHON, TOOL, *args], cwd=BASE, env=self.env,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=90)

    def test_list_json(self):
        result = self._run("list", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual(len(rows), len(ui_theme.SPEC))
        self.assertTrue(all("key" in row and "value" in row for row in rows))

    def test_set_then_diff_then_reset(self):
        result = self._run("set", "base.accent=#E04B3A")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("#E04B3A", result.stdout)

        result = self._run("diff")
        self.assertIn("base.accent", result.stdout)
        self.assertIn("btn.primaryBg", result.stdout)   # 引用跟着变，也要出现在 diff 里

        result = self._run("reset", "--all")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self._run("diff")
        self.assertIn("一致", result.stdout)

    def test_set_rejects_bad_value_without_writing(self):
        self._run("set", "base.accent=#E04B3A")
        before = _read_text(self.path)
        result = self._run("set", "base.ink=notacolor", "shadow.strength=45")
        self.assertEqual(result.returncode, 2, "校验失败必须是非零退出码")
        self.assertIn("没有写入", result.stdout)
        self.assertEqual(_read_text(self.path), before,
                         "全有或全无：一条不合法就一条都不写")

    def test_preset(self):
        result = self._run("preset", "ink")
        self.assertEqual(result.returncode, 0, result.stderr)
        values, _ = ui_theme.read_file(self.path)
        self.assertEqual(values["base.ink"], "#F2F2F0")
        self.assertEqual(values["shell.top"], "#0E1315")

    def test_get_unknown_key_exit_code(self):
        result = self._run("get", "btn.nope")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
