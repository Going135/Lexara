# -*- coding: utf-8 -*-
"""连续扫词的调度层（任务书 §6）：八条腿 = 同时踩词的能力，不是词数上限。

一句话：**结果列表和蜘蛛当前这一批目标是两件事。**

以前 `AimOverlay.__init__` 里一行 `words[:8]` 就把第 9 个之后的词全丢了 ——
用户框了一屏字幕，蜘蛛只踩八个，剩下的既不报错也不提示，属于「静默丢词」。
这里把这件事拆开：

* :class:`ScanTarget` —— 一个词的一次出现，带**稳定唯一的 `word_id`**。
  光用文本不够：同一句里 `the` 出现三次，三个都得有自己的框和自己的状态；
* :class:`ScanSession` —— 五个状态（pending / active / completed / skipped / failed）
  加一个「用户重试」的回退口子。每个目标**最多完成一次**，除非用户显式重试；
* 路径顺序：行优先（阅读顺序）+ 同一行内最近邻，保证蜘蛛不会在屏幕两头来回弹；
* 分批：一次最多给 `batch` 个（默认 8 = 腿数），空出来的腿再领下一批。

这个模块**刻意不 import Qt**：纯逻辑，能单测、能被覆盖层和（以后的）蜘蛛感应共用。
所有时间都从外面注入（`clock`），测试里不需要真的等秒。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

PENDING = "pending"
ACTIVE = "active"
COMPLETED = "completed"
SKIPPED = "skipped"
FAILED = "failed"

#: 腿数。八条腿是**同时**能踩多少词，不是总共能处理多少词。
LEG_COUNT = 8
#: 一批里所有目标都落定之后，停留多久再换下一批（秒）。
#: 太快换批会让人来不及看清哪个词被踩了；太慢像卡住。
DEFAULT_DWELL = 0.45
#: 单个目标最多领几次（防止「落不上就永远换不到下一批」的死循环）。
MAX_ATTEMPTS = 3
#: 一批开出去多久仍未全部落位，就算这次尝试失败（秒）。
#: 覆盖层的腿是平滑伸过去的，正常一帧到两帧就落位；超过这个时长说明
#: 这个词**这一批里根本派不到腿**（被更远的词挤掉了 / 中途坐标变了）。
#: 没有这一条，「领不到腿的目标」会把整条队列钉死在第一批上 ——
#: 任务书明令禁止静默丢词，所以这里给它一个有界的重试，重试耗尽判 failed。
DEFAULT_STALL = 0.9


def _point(item: dict):
    pos = item.get("screen_pos")
    if not pos:
        return None
    return (float(pos[0]), float(pos[1]))


def row_of(item: dict) -> int:
    """这个词属于第几「行」—— 按 y 中心做 1/2 词高的宽容分行。

    OCR 行高不同、轻微倾斜时，同一行的词 y 会差十几个像素；
    直接按 y 排序会把一行拆成两行、把阅读顺序打乱。
    """
    box = item.get("screen_box")
    if box:
        return int(round((box[1] + box[3] / 2.0) / 24.0))
    pos = _point(item)
    return int(round(pos[1] / 24.0)) if pos else 0


@dataclass
class ScanTarget:
    """一次选区里的一个词的一次出现。"""

    word_id: str
    item: dict
    state: str = PENDING
    attempts: int = 0
    #: 这批里是否真的派到了腿（False = 够不着，只亮框）
    pegged: bool = False
    landed_at: float | None = None
    reason: str = ""

    @property
    def word(self) -> str:
        return self.item.get("surface") or self.item.get("lemma") or ""

    @property
    def point(self):
        return _point(self.item)

    @property
    def done(self) -> bool:
        return self.state in (COMPLETED, SKIPPED, FAILED)


class ScanSession:
    """一次框选 = 一个 session。暂停/继续/取消都在这里，覆盖层只负责画。"""

    def __init__(self, words, batch: int = LEG_COUNT, clock=time.monotonic,
                 dwell: float = DEFAULT_DWELL, origin=None, source: str = "scan",
                 stall: float = DEFAULT_STALL):
        words = [w for w in (words or []) if _point(w)]
        self.clock = clock
        self.batch = max(1, int(batch))
        self.dwell = max(0.0, float(dwell))
        self.stall = max(0.05, float(stall))
        self.origin = origin                      # 蜘蛛当前位置（算第一批路径用）
        #: 换批回调：覆盖层挂一个函数进来（`on_batch(targets)`）
        self.on_batch = None
        #: 结束回调（全部处理完或被取消）
        self.on_finish = None
        self._cancelled = False
        self._paused = False
        self._batch_no = 0
        #: 当前批全部落定之后，什么时候允许开下一批（None = 还没到停留计时）
        self._dwell_until = None
        #: 当前批开出去的时刻（判「这批卡住了」用，见 `DEFAULT_STALL`）
        self._batch_started = None
        self._fired = False
        self.targets = self._build(words, source)
        self.order = self._ordered(self.targets)

    # ---------------------------------------------------------------- 构造
    @staticmethod
    def _build(words, source: str) -> list:
        """给每个词分配**稳定唯一**的 `word_id`。

        键里带上文本 + 该文本第几次出现，所以：
        * 同一个词出现三次 → `the#0 / the#1 / the#2`，三个独立目标；
        * 同一批结果重排、换批、暂停恢复，`word_id` 都不变（覆盖层的框靠它对齐）。
        """
        seen: dict = {}
        taken: set = set()
        targets = []
        for item in words:
            surface = (item.get("surface") or item.get("lemma") or "?").lower()
            index = seen.get(surface, 0)
            seen[surface] = index + 1
            word_id = "%s:%s#%d" % (source, surface, index)
            # ★ 用「空/冲突才改写」而不是 `setdefault`：上游 `OcrWorker` 给每个词卡
            #   预置了 `word_id: ""`（占位字段），`setdefault` 会把它当成已有值保留，
            #   于是框、点击、落位回执全都对不上号。
            #   反过来，同一个 session 被重建时（换批次、重开覆盖层）词卡上已经带着
            #   上一轮的 id，**沿用**它才能让框在原地不跳。
            existing = item.get("word_id")
            if existing and existing not in taken:
                word_id = existing
            else:
                while word_id in taken:        # 万一和沿用下来的 id 撞了
                    index += 1
                    word_id = "%s:%s#%d" % (source, surface, index)
                item["word_id"] = word_id
            seen[surface] = index
            taken.add(word_id)
            targets.append(ScanTarget(word_id=word_id, item=item))
        return targets

    @staticmethod
    def _ordered(targets: list) -> list:
        """行优先阅读顺序；同一行内从上一个落点做最近邻。"""
        rows: dict = {}
        for target in targets:
            rows.setdefault(row_of(target.item), []).append(target)
        ordered = []
        cursor = None
        for row_key in sorted(rows):
            row = rows[row_key]
            if cursor is None:
                # 第一行：最靠左的就是起点（阅读顺序优先于「离蜘蛛最近」）
                row.sort(key=lambda t: t.point[0])
                cursor = row[0].point
            else:
                pool = list(row)
                chain = []
                while pool:
                    nxt = min(pool, key=lambda t: math.dist(cursor, t.point))
                    pool.remove(nxt)
                    chain.append(nxt)
                    cursor = nxt.point
                row = chain
            ordered.extend(row)
        return ordered

    # ---------------------------------------------------------------- 状态查询
    def by_state(self, *states) -> list:
        return [t for t in self.targets if t.state in states]

    def pending(self) -> list:
        """待办目标，按**规划好的阅读顺序**排。

        这里必须走 `self.order` 而不是 `self.targets`：后者是 OCR 给词的顺序，
        领批次如果按它排，多行选区会变成「先踩最后一行、再回头踩第一行」。
        """
        return [t for t in self.order if t.state == PENDING]

    def active(self) -> list:
        return self.by_state(ACTIVE)

    def stats(self) -> dict:
        counts = {state: 0 for state in
                  (PENDING, ACTIVE, COMPLETED, SKIPPED, FAILED)}
        for target in self.targets:
            counts[target.state] += 1
        pegged = sum(1 for t in self.targets
                     if t.state == COMPLETED and t.pegged)
        return {"total": len(self.targets),
                "recognized": len(self.targets),
                "pending": counts[PENDING], "active": counts[ACTIVE],
                "completed": counts[COMPLETED], "skipped": counts[SKIPPED],
                "failed": counts[FAILED],
                # 「完成」里有两种：真的被腿踩到的、和够不着只亮框的。
                # 界面上要分开说，不然「24 个全完成」会把「6 个没踩到」藏起来。
                "pegged": pegged, "box_only": counts[COMPLETED] - pegged,
                "batches": self._batch_no,
                "remaining": counts[PENDING] + counts[ACTIVE],
                "cancelled": self._cancelled, "paused": self._paused}

    def summary(self) -> dict:
        """`stats()` 的别名 —— 协作契约（`communite/contracts/`）里
        WorkBuddy 按 `ScanSession.summary()` 认这组字段，两个名字都给，
        免得他那边要改口。"""
        return self.stats()

    @property
    def finished(self) -> bool:
        return self._cancelled or not (
            any(t.state in (PENDING, ACTIVE) for t in self.targets))

    # ---------------------------------------------------------------- 调度
    def start(self) -> list:
        """领第一批。**可重复调用**：已经在途就直接返回在途的那一批。

        写成幂等是因为覆盖层和调用方都可能二次 `start()`（重建覆盖层、
        测试里先手动开一批）—— 非幂等版本会把在途批次的 `on_batch` 丢掉，
        表现是「腿收回来了却没有再伸出去」。
        """
        in_flight = self.active()
        if in_flight:
            return in_flight
        return self._open_batch()

    def _open_batch(self) -> list:
        if self._cancelled or self._paused:
            return []
        picked = self.pending()[:self.batch]
        if not picked:
            # 没有待办了：可能全做完了，也可能剩下的都被 skip/fail 掉了
            self._dwell_until = None
            self._batch_started = None
            self._finish_once()
            return []
        self._batch_no += 1
        for target in picked:
            target.state = ACTIVE
            target.attempts += 1
            target.pegged = False
            target.landed_at = None
        self._dwell_until = None          # 新一批：停留计时重新开始
        self._batch_started = self.clock()
        if self.on_batch:
            self.on_batch(picked)
        return picked

    def advance(self, force: bool = False) -> list:
        """换下一批。当前批还有腿没落位时，除非 `force`，否则不换。"""
        if self._paused or self._cancelled:
            return []
        waiting = [t for t in self.active() if t.landed_at is None]
        if waiting and not force:
            return []
        return self._open_batch()

    def tick(self, now: float | None = None) -> list:
        """覆盖层每帧调一次：推进停留计时，到点就换下一批。

        换批条件（任务书 §6.4「空出来的腿再领下一批」）：
        当前批**全部落定**（踩上 / 够不着只亮框 / 失败）之后，
        再停留 `dwell` 秒让人看清，然后开下一批。

        ★ 还有一个「这批卡住了」的出口（`DEFAULT_STALL`）：
        派不到腿的目标既不会落位也不会失败，光靠停留计时永远换不了批 ——
        于是它超时后被打回待办、立刻重开一批让腿重新分配；
        反复 `MAX_ATTEMPTS` 轮仍落不上的判 **failed** 并写明原因。
        这是「不许静默丢词」的最后一道保险：队列要么走完，要么如实报告。
        """
        if self._paused or self._cancelled:
            return []
        if now is None:
            now = self.clock()
        waiting = [t for t in self.active() if t.landed_at is None]
        if waiting and self._batch_started is not None \
                and now - self._batch_started >= self.stall:
            for target in waiting:
                if target.attempts >= MAX_ATTEMPTS:
                    self.mark_failed(target.word_id, "多次尝试仍未落位")
            still = [t for t in self.active() if t.landed_at is None]
            if still:
                for target in still:
                    target.state = PENDING
                return self._open_batch()
            waiting = []
        if waiting:
            return []
        if not self.active() and self._dwell_until is None:
            # 一批刚被外部结清（或第一批）：立刻开下一批
            return self._open_batch() if self.pending() else self._finish_once() or []
        if self._dwell_until is not None and now >= self._dwell_until:
            return self._open_batch()
        return []

    # ---------------------------------------------------------------- 落位
    def note_progress(self) -> None:
        """宿主报告「这一批正在实质前进」：把「这批卡住了」的计时续期。

        任务书 §8 之后，覆盖层的身体会沿路径**挨个走过去**踩：一批 8 个词散布
        在一大片区域时，走完一圈要好几秒，而每个停靠点上等腿落位也要时间。
        这些时间累加起来会超过 `stall`，于是 `tick()` 会把还没轮到的词打回
        pending 重开一批 —— 三次之后全判 failed（一个词都没踩到）。
        所以每落到一个停靠点就调一次这里：语义是「队列在动，别急着重试」。

        只在批次真的在途时续期：`_batch_started` 为 None 说明还没开批或已结清，
        那时续期会凭空造出一个计时起点。
        """
        if self._batch_started is not None:
            self._batch_started = self.clock()

    def mark_landed(self, word_id: str, pegged: bool = True) -> bool:
        """一个目标完成。**最多完成一次**：已经 done 的目标再调也不会重复计数。"""
        target = self.get(word_id)
        if target is None or target.state == COMPLETED:
            return False
        if target.state not in (ACTIVE, PENDING):
            return False
        target.state = COMPLETED
        target.pegged = pegged
        target.landed_at = self.clock()
        # 这一批全落定了 → 开始算停留时间，到点换下一批
        if not any(t.landed_at is None for t in self.active()):
            self._dwell_until = self.clock() + self.dwell
        return True

    def mark_failed(self, word_id: str, reason: str = "") -> bool:
        target = self.get(word_id)
        if target is None or target.state == FAILED:
            return False
        if target.state == COMPLETED:
            return False
        target.state = FAILED
        target.reason = reason[:200]
        return True

    def skip(self, word_id: str, reason: str = "用户跳过") -> bool:
        target = self.get(word_id)
        if target is None or target.state == SKIPPED:
            return False
        if target.state == COMPLETED:
            return False
        target.state = SKIPPED
        target.reason = reason[:200]
        return True

    def retry(self, word_id: str) -> bool:
        """用户显式重试：唯一能让已完成目标重新回到待办的入口。"""
        target = self.get(word_id)
        if target is None:
            return False
        target.state = PENDING
        target.attempts = 0
        target.landed_at = None
        target.pegged = False
        target.reason = ""
        return True

    def get(self, word_id: str):
        for target in self.targets:
            if target.word_id == word_id:
                return target
        return None

    # ---------------------------------------------------------------- 控制
    def pause(self) -> None:
        """暂停：不再领新批，在途这一批保持原样（腿不收回，只是不再推进）。"""
        self._paused = True

    def resume(self) -> None:
        self._paused = False
        self._dwell_until = None
        # 卡住计时重新开始算：暂停的那段时间不该算成「这批落位太慢」，
        # 否则用户暂停久一点，回来立刻触发超时重试。
        if self.active():
            self._batch_started = self.clock()

    @property
    def paused(self) -> bool:
        return self._paused

    def cancel(self) -> None:
        """取消：所有未落定的目标一次性结清，**不允许有词悬在中间**。"""
        if self._cancelled:
            return
        self._cancelled = True
        for target in self.targets:
            if target.state in (PENDING, ACTIVE):
                target.state = SKIPPED
                target.reason = "用户停止扫描"
        self._finish_once()

    def _finish_once(self) -> None:
        if getattr(self, "_fired", False):
            return
        if not self.finished and not self._cancelled:
            return
        self._fired = True
        if self.on_finish:
            self.on_finish(self.stats())

    # ---------------------------------------------------------------- 呈现
    def visible(self) -> list:
        """覆盖层这一帧该画框的目标：已完成的（历史批次）+ 当前批。

        分批重新定位时**旧批次的框不消失**，否则用户看到的是一闪一闪地丢词；
        蜘蛛会走过去踩新的，框留在原地。
        """
        return [t for t in self.targets
                if t.state in (COMPLETED, ACTIVE)]

    def current_batch(self) -> list:
        return self.active()

    def next_batch(self) -> list:
        """预览下一批（给「还剩 N 个」的提示用，不改状态）。"""
        return self.pending()[:self.batch]
