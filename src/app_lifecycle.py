# -*- coding: utf-8 -*-
"""桌宠生命周期（部署 / 收回 / 退出 / 启动后自动部署一次）。

为什么要单独一个模块（2026-10-18，任务书 §4 / §6）
----------------------------------------------------
原来这四条逻辑以闭包形式写在 `main.main()` 里，`app._pet` 就是一个裸引用：
- 没法写单测（`main()` 一旦被 import 就会跑整个入口）；
- 「同一个状态被触发两次」全靠每个调用点自己记得判断；
- 收回时的清理散落在 `on_recall` / `on_recall_from_pet` / `on_quit` 三处，
  任何一处漏掉就会留下窗口或回调。

现在收成一个对象，**创建之前先看现有实例**、**销毁之后把引用清空**，
并且把「动画没跑完时的重复点击」收敛成 `launcher` 已有的相位机
（`idle / deploying / deployed / recalling`，非目标相位直接忽略）。

设计约束（不改业务）：
- 只负责桌宠窗口与覆盖层的生死，不碰 OCR / 词库 / 复习；
- 皮肤同步仍然回到 `pet.set_skin()`，不新建第二条链路；
- 自动部署只在**进程启动**时最多尝试一次（托盘恢复 / 收回 / 再显示不算）。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication


class PetLifecycle(QObject):
    """桌宠窗口的唯一管理者。

    ``pet_factory`` 可注入（测试里给一个只统计生命周期的假对象）；
    默认惰性导入 `pet_window.PetWindow`，避免在只需要设置界面的进程里
    把桌宠模块（含 OCR / 托盘）拖进来。
    """

    def __init__(self, launcher, lexicon, book, settings, log=None,
                 pet_factory=None, parent=None):
        super().__init__(parent)
        self.launcher = launcher
        self.lexicon = lexicon
        self.book = book
        self.settings = settings
        self.log = log or (lambda message: None)
        self._factory = pet_factory or self._default_factory
        self._pet = None
        #: 自动部署只允许发生一次（每次进程启动一个生命周期对象）
        self._auto_deploy_done = False
        #: 统计：测试和探针用它断言「没有累积窗口」
        self.created = 0
        self.destroyed = 0

    # ------------------------------------------------ 只读
    @property
    def pet(self):
        return self._pet

    def _default_factory(self, payload: dict):
        from pet_window import PetWindow
        pet = PetWindow(self.lexicon, self.book, settings=self.settings)
        pet.apply_settings(payload)
        return pet

    # ------------------------------------------------ 接线
    def wire(self) -> None:
        """把启动台的三个信号接到本对象（幂等：重复调用不会重复连接）。

        用显式标记而不是「先 disconnect 再 connect」：PySide 对未连接的槽发
        disconnect 只会打一条 RuntimeWarning（不抛异常），try/except 拦不住，
        反而在日志里留一堆噪音。
        """
        if getattr(self, "_wired", False):
            return
        self._wired = True
        self.launcher.deploy_requested.connect(self.deploy)
        self.launcher.recall_requested.connect(self.recall)
        self.launcher.quit_requested.connect(self.quit_app)

    # ------------------------------------------------ 部署
    def deploy(self, payload: dict) -> bool:
        """创建桌宠。已有实例时**不创建第二个**，返回 False。"""
        if self._pet is not None:
            self.log("[lifecycle] 已有桌宠，忽略重复部署")
            return False
        try:
            pet = self._factory(payload or {})
        except Exception as error:              # noqa: BLE001
            self.log("[lifecycle] 创建桌宠失败：%r" % (error,))
            # 动画已经播完但桌宠没起来 —— 把相位打回 idle，别让按钮卡在「收回」
            self._recover_to_idle()
            return False
        try:
            pet.apply_settings(payload or {})
        except Exception as error:              # noqa: BLE001
            self.log("[lifecycle] 应用设置失败：%r" % (error,))
        pet.recall_callback = self.recall_from_pet
        self._pet = pet
        self.created += 1
        self.log("[lifecycle] 桌宠已创建（第 %d 次）" % self.created)
        return True

    # ------------------------------------------------ 设置实时同步
    def sync_skin(self, skin_id: str) -> None:
        """启动台换皮肤 → 已部署的桌宠**立刻**换皮，不必重新部署。

        `persist=False`：settings 是启动台刚写的（`_on_skin_selected`），
        桌宠这边跟着显示就行，别再多写一次磁盘。
        """
        pet = self._pet
        if pet is None:
            return
        try:
            pet.set_skin(str(skin_id), persist=False)
        except Exception as error:              # noqa: BLE001
            self.log("[lifecycle] 同步皮肤失败：%r" % (error,))
            return
        self.log("[lifecycle] 皮肤已同步到桌宠 → %s" % skin_id)

    def sync_scale(self, scale: float) -> None:
        """启动台改「桌宠大小」→ 已部署的桌宠**立刻**重算几何。

        2026-10-18：以前 `pet_scale` 只写 settings，`PetWindow.set_scale()`
        只在部署时被 `apply_settings()` 调一次，于是部署之后再拖滑杆，
        桌面上毫无反应（用户报的「调大小对蜘蛛没有作用」）。
        """
        pet = self._pet
        if pet is None:
            return
        try:
            pet.set_scale(float(scale))
        except Exception as error:              # noqa: BLE001
            self.log("[lifecycle] 同步大小失败：%r" % (error,))
            return
        self.log("[lifecycle] 桌宠大小 → %d%%" % round(float(scale) * 100))

    def _recover_to_idle(self) -> None:
        launcher = self.launcher
        if getattr(launcher, "phase", "") != "idle":
            try:
                launcher.phase = "idle"
                launcher.jar.set_phase("idle")
                launcher._set_deploy_buttons("deploy", "部 署", True)
            except Exception:                   # noqa: BLE001
                pass

    # ------------------------------------------------ 收回
    def recall(self) -> None:
        """启动台点「收回」→ 只销毁桌宠，不动启动台自身。"""
        self._destroy_pet("收回")

    def recall_from_pet(self) -> None:
        """桌宠右键「回到启动台」→ 销毁桌宠 + 走同一条收回时间轴。"""
        self._destroy_pet("从桌宠收回")
        self.launcher.recall_from_pet()

    def _destroy_pet(self, reason: str) -> None:
        pet = self._pet
        if pet is None:
            return
        self._pet = None                        # 先摘引用：shutdown 里的回调不会再进来
        try:
            pet.shutdown()
        except Exception as error:              # noqa: BLE001
            self.log("[lifecycle] 销毁桌宠时出错：%r" % (error,))
        self.destroyed += 1
        self.log("[lifecycle] 桌宠已销毁（%s，累计 %d）" % (reason, self.destroyed))

    # ------------------------------------------------ 退出
    def quit_app(self) -> None:
        self._destroy_pet("退出应用")
        QApplication.quit()

    # ------------------------------------------------ 启动后默认部署
    def auto_deploy_once(self) -> bool:
        """进程启动后**最多**自动部署一次（§6）。

        返回 True 表示这次真的发起了部署。以下情况一律不部署并且**不算失败**：
        - 用户关掉了「启动后默认部署蜘蛛」；
        - 本进程已经尝试过（`_auto_deploy_done`）；
        - 已有桌宠，或启动台不在 `idle`（动画在跑 / 已部署）。
        """
        if self._auto_deploy_done:
            return False
        self._auto_deploy_done = True
        if not bool(self.settings.get("auto_deploy_on_start", True)):
            self.log("[lifecycle] 自动部署：设置已关闭，停留启动台")
            return False
        if self._pet is not None:
            self.log("[lifecycle] 自动部署：已有桌宠，跳过")
            return False
        phase = getattr(self.launcher, "phase", "idle")
        if phase != "idle":
            self.log("[lifecycle] 自动部署：相位为 %s，跳过" % phase)
            return False
        self.log("[lifecycle] 自动部署：开始")
        self.launcher.begin_deploy()
        return True

    def schedule_auto_deploy(self, delay_ms: int = 900) -> None:
        """初始化完成后排一次自动部署（带 context object，退出时自动取消）。"""
        QTimer.singleShot(delay_ms, self, self.auto_deploy_once)
