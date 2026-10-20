# -*- coding: utf-8 -*-
"""开机自启动（任务书 §5）。

验收要点（全部用**临时目录**当启动文件夹，绝不碰真实的
`%APPDATA%\\...\\Startup`）：

1. **幂等** —— 连续开启两次，目录里只有一个 `Lexara.lnk`；
2. **可关闭** —— 关闭后文件消失，再关闭一次也返回成功；
3. **状态以文件为准** —— `state()` 不读任何设置位，文件在就是开；
4. **失败说实话** —— 目录不存在 / PowerShell 不可用时返回 ok=False 加原因，
   不给用户「已经帮你设好了」的假象；
5. **目标正确** —— 开发态指向 python + src/main.py（打包态指向 exe）。

运行：  python test/test_autostart.py
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import autostart


class AutostartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lexara_startup_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _shortcuts(self):
        return [name for name in os.listdir(self.tmp)
                if name.lower().endswith(".lnk")]

    def test_state_is_file_based(self):
        state = autostart.state(self.tmp)
        self.assertFalse(state["enabled"])
        self.assertTrue(state["path"].startswith(self.tmp))
        self.assertIn("supported", state)

    def test_enable_is_idempotent(self):
        first = autostart.enable(self.tmp)
        if not first.get("ok"):
            # 没有 PowerShell / 被策略拦住的机器：允许失败，但必须给出原因，
            # 而且不能留下半个启动项。
            self.assertTrue(first.get("message"))
            self.assertFalse(first.get("enabled"))
            self.assertEqual(self._shortcuts(), [])
            return
        second = autostart.enable(self.tmp)
        self.assertTrue(second.get("ok"))
        self.assertEqual(self._shortcuts(), [autostart.SHORTCUT_NAME])
        self.assertTrue(autostart.state(self.tmp)["enabled"])

    def test_disable_removes_only_our_shortcut(self):
        other = os.path.join(self.tmp, "SomeoneElse.lnk")
        with open(other, "wb") as handle:
            handle.write(b"not really a shortcut")
        autostart.enable(self.tmp)
        result = autostart.disable(self.tmp)
        self.assertTrue(result.get("ok"), result.get("message"))
        self.assertFalse(autostart.state(self.tmp)["enabled"])
        self.assertTrue(os.path.isfile(other))        # 别人的启动项不许动
        again = autostart.disable(self.tmp)
        self.assertTrue(again.get("ok"))              # 幂等

    def test_enable_reports_missing_directory(self):
        missing = os.path.join(self.tmp, "no-such-folder")
        result = autostart.enable(missing)
        self.assertFalse(result.get("ok"))
        self.assertTrue(result.get("message"))

    def test_launch_target_points_at_project(self):
        target, arguments, workdir, _icon = autostart.launch_target()
        self.assertTrue(target)
        if getattr(sys, "frozen", False):
            self.assertEqual(arguments, "")
        else:
            self.assertIn("main.py", arguments)
            self.assertTrue(os.path.isdir(workdir))

    def test_help_text_explains_how_to_disable(self):
        text = autostart.help_text()
        self.assertIn(autostart.SHORTCUT_NAME, text)
        self.assertIn("关闭", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
