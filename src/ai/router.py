"""Context analyzer and history-aware learning selector, with safe fallback."""
from .cloud_provider import CloudAIProvider
from .schemas import validate


class LearningRouter:
    def __init__(self, provider=None):
        self.provider = provider or CloudAIProvider()

    def prepare_local(self, text, candidates, history, mode, limit):
        """**默认识词链路**用这个：只做本地规则排序 + 词典标注，一次网络都不发。

        任务书 §5.1：`截图 → OCR → 词级切分 → 本地词典 → 八腿落位 → 结果卡`
        这条主链路里不能出现云端调用。以前的 `select()` 在默认链路里同步调
        `provider.analyze()`，没配 key 时靠异常兜底（还算一次 HTTPS 前置检查），
        配了 key 就要等 12 秒 —— 用户感知是「蜘蛛踩词慢了一大截」，
        而它拿到的好处只是把本地已有的释义换了个说法。

        与 `select()` 的区别：
        * `source='local'`，`context_meaning` 就是词典释义本身，不编理由；
        * `limit` **不再夹到 8**。八条腿是「同时踩词的能力」，不是词数上限
          （§6），连续扫词要靠 `scan_session` 分批，这里先把闸门拆了；
        * 不实例化、不触碰 provider，测试里也不需要 mock 网络。

        `ai_requested=False` 是结果卡上那颗「AI 语境分析与造句」按钮的判据：
        按钮点了才会走 `ai/context_request.py`。
        """
        limit = max(1, int(limit))
        by_word = {i.get('word', '').lower(): i for i in history}
        available = []
        for candidate in candidates:
            item = dict(candidate)
            previous = by_word.get(item['lemma'].lower(), {})
            if previous.get('stage', -1) >= 3 and previous.get('correct', 0) > previous.get('wrong', 0):
                continue
            item['learning'] = {k: previous.get(k, 0) for k in ('stage', 'correct', 'wrong')}
            available.append(item)
        # Preserve syllabus ordering, while prioritizing words with recorded mistakes.
        available.sort(key=lambda c: (c.get('off_syllabus', False),
                                      -c['learning']['wrong']))
        words = []
        for item in available[:limit]:
            words.append(dict(
                item,
                context_meaning=item.get('meaning', ''),
                ai_reason='',
                ai_confidence=None,
                collocations=[],
                ai_requested=False,
                # 截图里的原句仍然带上：结果卡的 AI 按钮要靠它组 prompt，
                # 没有 AI 结果时也不显示成「AI 解释」。
                context_sentence=text[:6000],
                ai_source='local',
                sentence_meaning='',
                ai_candidate_count=len(candidates),
                ai_eligible_count=len(available)))
        return words, {'source': 'local', 'reason': '',
                       'candidate_count': len(candidates),
                       'eligible_count': len(available)}

    def select(self, text, candidates, history, mode, limit):
        """云端选词重排。**不在默认识词链路上**（§5.1），保留给显式调用。

        默认链路请用 :meth:`prepare_local`。这里保留原签名和原兜底行为，
        是为了 `communite/contracts/ai-provider-contract.md` 里说好的兼容性：
        WorkBuddy 的对话/选词功能随时可以调它，Qoder 侧不会再把它塞回 OCR 主链路。
        """
        limit = max(1, min(8, limit))
        by_word = {i.get('word', '').lower(): i for i in history}
        available = []
        for candidate in candidates:
            item = dict(candidate)
            previous = by_word.get(item['lemma'].lower(), {})
            if previous.get('stage', -1) >= 3 and previous.get('correct', 0) > previous.get('wrong', 0):
                continue
            item['learning'] = {k: previous.get(k, 0) for k in ('stage', 'correct', 'wrong')}
            available.append(item)
        # Preserve syllabus ordering, while prioritizing words with recorded mistakes.
        available.sort(key=lambda c: (c.get('off_syllabus', False),
                                      -c['learning']['wrong']))
        if not available:
            return [], {'source': 'rules', 'reason': '没有未掌握的候选词'}
        try:
            payload = self.provider.analyze(text, available[:48], mode, limit)
            words = validate(payload, available[:48], limit)
            sentence_meaning = payload.get('sentence_meaning', '')
            if not isinstance(sentence_meaning, str):
                raise ValueError('Invalid sentence meaning')
            source, reason = 'cloud', ''
        except Exception as error:
            words = [dict(c, context_meaning=c.get('meaning', ''),
                          ai_reason='结合当前词表与复习记录，建议学习这个词。',
                          ai_confidence=None, collocations=[]) for c in available[:limit]]
            sentence_meaning = ''
            source = 'rules'
            # Avoid exposing credentials, response bodies or network details in UI/logs.
            reason = '云端 AI 未配置或暂不可用，已使用本地词库与规则。'
        for item in words:
            item.update(ai_source=source, context_sentence=text[:6000],
                        sentence_meaning=sentence_meaning[:1000],
                        ai_candidate_count=len(candidates),
                        ai_eligible_count=len(available))
        return words, {'source': source, 'reason': reason,
                       'candidate_count': len(candidates), 'eligible_count': len(available)}
