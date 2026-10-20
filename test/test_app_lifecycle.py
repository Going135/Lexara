# -*- coding: utf-8 -*-
"""桌宠生命周期回归（任务书 §4 / §6）。

钉的是「部署/收回被触发两次」这一类最贵的 bug：

1. **重复部署不产生第二个桌宠** —— 动画期间连点、托盘菜单再点一次，
   都只允许有 1 个 `PetWindow`；
2. **收回是幂等的** —— 已经收回了再收一次，不新增销毁、不抛异常；
3. **销毁后引用必须清空** —— 否则下一次部署会拿到已析构的 QObject
   （这正是 10-18 那次「收回后闪退」的同一类根因）；
4. **自动部署只发生一次** —— 托盘恢复 / 收回 / 再显示都不许再触发（§6）；
5. **wire() 幂等** —— 重复接线不能让一次点击创建两个桌宠。

运行：  python test/test_app_lifecycle.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from app_lifecycle import PetLifecycle


class FakeJar(QObject):
    def __init__(self):
        super().__init__()
        self.phases = []

    def set_phase(self, phase):
        self.phases.append(phase)


class FakeLauncher(QObject):
    deploy_requested = Signal(dict)
    recall_requested = Signal()
    quit_requested = Signal()

    def __init__(self):
        super().__init__()
        self.phase = "idle"
        self.jar = FakeJar()
        self.deploys = 0
        self.recalls_from_pet = 0
        self.button_states = []

    def begin_deploy(self):
        self.deploys += 1
        self.phase = "deploying"

    def recall_from_pet(self):
        self.recalls_from_pet += 1

    def _set_deploy_buttons(self, *args):
        self.button_states.append(args)


class FakePet(QObject):
    """只记录生命周期，不碰 OCR / 托盘 / 动画。"""

    created = 0

    def __init__(self):
        super().__init__()
        FakePet.created += 1
        self.shutdowns = 0
        self.applied = []
        self.skins = []                       # (skin_id, persist)
        self.scales = []
        self.recall_callback = None
        self.alive = True

    def apply_settings(self, payload):
        self.applied.append(payload)

    def set_skin(self, skin_id, persist=True):
        self.skins.append((skin_id, persist))
        return True

    def set_scale(self, value):
        self.scales.append(value)

    def shutdown(self):
        self.shutdowns += 1
        self.alive = False


class FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


def _make(settings=None):
    launcher = FakeLauncher()
    pets = []

    def factory(payload):
        pet = FakePet()
        pets.append(pet)
        return pet

    lifecycle = PetLifecycle(launcher, None, None,
                             settings or FakeSettings(),
                             pet_factory=factory)
    return launcher, lifecycle, pets


class DeployRecallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # QObject / Signal 需要 QApplication；不建窗口，也不会弹任何界面。
        # 刻意**不**设 QT_QPA_PLATFORM=offscreen（项目已知坑：会让 OCR 假失败，
        # 且这里要的是和线上一致的 QPA 行为）。
        cls.app = QApplication.instance() or QApplication([])

    def test_double_deploy_creates_one_pet(self):
        launcher, lifecycle, pets = _make()
        self.assertTrue(lifecycle.deploy({"skin": "a"}))
        self.assertFalse(lifecycle.deploy({"skin": "a"}))
        self.assertEqual(len(pets), 1)
        self.assertEqual(lifecycle.created, 1)
        self.assertEqual(pets[0].applied, [{"skin": "a"}])

    def test_recall_is_idempotent(self):
        _, lifecycle, pets = _make()
        lifecycle.deploy({})
        lifecycle.recall()
        self.assertIsNone(lifecycle.pet)
        lifecycle.recall()                      # 再收一次：不崩、不重复销毁
        self.assertEqual(pets[0].shutdowns, 1)
        self.assertEqual(lifecycle.destroyed, 1)

    def test_redeploy_after_recall_uses_fresh_pet(self):
        _, lifecycle, pets = _make()
        lifecycle.deploy({})
        lifecycle.recall()
        self.assertTrue(lifecycle.deploy({}))
        self.assertEqual(len(pets), 2)
        self.assertIs(lifecycle.pet, pets[1])
        self.assertTrue(pets[1].alive)

    def test_recall_from_pet_reaches_both_sides(self):
        launcher, lifecycle, pets = _make()
        lifecycle.deploy({})
        # 绑定方法每次取都是新对象，比较 __self__ / __func__ 才准
        self.assertIs(pets[0].recall_callback.__self__, lifecycle)
        self.assertIs(pets[0].recall_callback.__func__,
                      PetLifecycle.recall_from_pet)
        pets[0].recall_callback()
        self.assertEqual(pets[0].shutdowns, 1)
        self.assertEqual(launcher.recalls_from_pet, 1)
        self.assertIsNone(lifecycle.pet)

    def test_factory_failure_does_not_leave_phase_hanging(self):
        launcher = FakeLauncher()
        launcher.phase = "deploying"

        def broken(payload):
            raise RuntimeError("boom")

        lifecycle = PetLifecycle(launcher, None, None, FakeSettings(),
                                 pet_factory=broken)
        self.assertFalse(lifecycle.deploy({}))
        self.assertIsNone(lifecycle.pet)
        self.assertEqual(launcher.phase, "idle")   # 按钮不会卡在「收回」
        self.assertIn("idle", launcher.jar.phases)

    def test_wire_is_idempotent(self):
        launcher, lifecycle, pets = _make()
        lifecycle.wire()
        lifecycle.wire()
        launcher.deploy_requested.emit({})
        self.assertEqual(len(pets), 1)

    def test_quit_destroys_pet(self):
        _, lifecycle, pets = _make()
        lifecycle.deploy({})
        lifecycle.quit_app()
        self.assertEqual(pets[0].shutdowns, 1)
        self.assertIsNone(lifecycle.pet)


class LiveSyncTests(unittest.TestCase):
    """启动台改设置 → 已部署的桌宠实时跟随（2026-10-18 用户反馈两条 bug）。

    历史：`skin_changed` 早就有了，但部署时发的 `payload["skin"]` 读的是隐藏
    面板，QML 换皮不经过面板；`pet_scale` 更彻底 —— 只写 settings，没有任何
    地方调 `pet.set_scale()`。所以「切换皮肤后部署仍是原皮肤」「调大小对蜘蛛
    没作用」。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_skin_reaches_deployed_pet(self):
        launcher, lifecycle, pets = _make()
        lifecycle.deploy({"skin": "white_jump_spider"})
        lifecycle.sync_skin("milk_spider")
        self.assertEqual(pets[0].skins, [("milk_spider", False)],
                         "换皮必须同步到桌宠，且不再二次写盘（persist=False）")

    def test_skin_without_pet_is_noop(self):
        launcher, lifecycle, pets = _make()
        lifecycle.sync_skin("milk_spider")      # 没部署：不许抛、不许造桌宠
        self.assertEqual(pets, [])

    def test_scale_reaches_deployed_pet(self):
        launcher, lifecycle, pets = _make()
        lifecycle.deploy({"pet_scale": 1.0})
        lifecycle.sync_scale(0.8)
        self.assertEqual(pets[0].scales, [0.8],
                         "拖大小滑杆必须真的调到 PetWindow.set_scale()")

    def test_scale_survives_pet_exception(self):
        """桌宠抛异常也不能把信号链打断（后面还要继续改大小）。"""
        launcher, lifecycle, pets = _make()
        lifecycle.deploy({})
        pets[0].set_scale = lambda v: (_ for _ in ()).throw(RuntimeError("boom"))
        lifecycle.sync_scale(1.2)               # 不抛就算过
        lifecycle.sync_scale(1.3)


class AutoDeployTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_auto_deploy_only_once(self):
        launcher, lifecycle, _ = _make(FakeSettings({"auto_deploy_on_start": True}))
        self.assertTrue(lifecycle.auto_deploy_once())
        self.assertEqual(launcher.deploys, 1)
        # 托盘恢复 / 收回 / 再显示都不该再来一次
        self.assertFalse(lifecycle.auto_deploy_once())
        self.assertEqual(launcher.deploys, 1)

    def test_auto_deploy_respects_setting(self):
        launcher, lifecycle, _ = _make(FakeSettings({"auto_deploy_on_start": False}))
        self.assertFalse(lifecycle.auto_deploy_once())
        self.assertEqual(launcher.deploys, 0)

    def test_auto_deploy_skips_when_not_idle(self):
        launcher, lifecycle, _ = _make(FakeSettings({"auto_deploy_on_start": True}))
        launcher.phase = "deployed"
        self.assertFalse(lifecycle.auto_deploy_once())
        self.assertEqual(launcher.deploys, 0)

    def test_auto_deploy_skips_when_pet_exists(self):
        launcher, lifecycle, _ = _make(FakeSettings({"auto_deploy_on_start": True}))
        lifecycle.deploy({})
        self.assertFalse(lifecycle.auto_deploy_once())
        self.assertEqual(launcher.deploys, 0)

    def test_setting_defaults_to_enabled(self):
        """缺省（老 settings.json 没这个键）时默认部署，符合 §6 的建议默认。"""
        launcher, lifecycle, _ = _make(FakeSettings())
        self.assertTrue(lifecycle.auto_deploy_once())
        self.assertEqual(launcher.deploys, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
