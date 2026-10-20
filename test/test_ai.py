import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from ai.router import LearningRouter
from ai.schemas import validate


class Provider:
    def analyze(self, *args):
        return {'sentence_meaning': '公司加快扩张。', 'targets': [
            {'word': 'accelerate', 'meaning': '加快', 'reason': '核心动作词',
             'priority': .9, 'confidence': .95, 'collocations': ['accelerate growth']},
            {'word': 'hallucination', 'meaning': '假词', 'reason': '',
             'priority': 1, 'confidence': 1}]}


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [{'lemma': 'accelerate', 'surface': 'accelerated',
                            'meaning': '加速', 'screen_pos': (123, 456)}]

    def test_context_and_coordinate_preserved(self):
        words, meta = LearningRouter(Provider()).select('accelerated', self.candidates, [], 'cet6', 8)
        self.assertEqual(meta['source'], 'cloud')
        self.assertEqual(len(words), 1)
        self.assertEqual(words[0]['screen_pos'], (123, 456))
        self.assertEqual(words[0]['surface'], 'accelerated')
        self.assertEqual(words[0]['context_meaning'], '加快')

    def test_failure_falls_back(self):
        with patch.object(Provider, 'analyze', side_effect=TimeoutError):
            words, meta = LearningRouter(Provider()).select('text', self.candidates, [], 'cet6', 8)
        self.assertEqual(meta['source'], 'rules')
        self.assertEqual(words[0]['meaning'], '加速')

    def test_mastered_filtered(self):
        words, _ = LearningRouter(Provider()).select('text', self.candidates,
            [{'word': 'accelerate', 'stage': 3, 'correct': 4, 'wrong': 0}], 'cet6', 8)
        self.assertEqual(words, [])

    def test_malformed_rejected(self):
        with self.assertRaises(ValueError):
            validate({'targets': []}, self.candidates, 8)


class LocalFirstTests(unittest.TestCase):
    """任务书 §5.1：默认识词链路 = 本地词典，一次网络都不发。"""

    def setUp(self):
        self.candidates = [
            {'lemma': 'accelerate', 'surface': 'accelerated', 'meaning': '加速'},
            {'lemma': 'thunder', 'surface': 'thunder', 'meaning': '雷',
             'off_syllabus': True},
        ]

    def test_prepare_local_never_touches_the_provider(self):
        class ExplodingProvider:
            def analyze(self, *args, **kwargs):
                raise AssertionError('默认链路里不允许调云端 provider')
        words, meta = LearningRouter(ExplodingProvider()).prepare_local(
            'The committee accelerated the project.', self.candidates, [], 'cet6', 8)
        self.assertEqual(meta['source'], 'local')
        self.assertEqual(len(words), 2)
        self.assertEqual(words[0]['lemma'], 'accelerate')   # 考纲词排在词表外之前
        for item in words:
            self.assertEqual(item['ai_source'], 'local')
            self.assertFalse(item['ai_requested'])
            self.assertEqual(item['context_meaning'], item['meaning'])
            self.assertEqual(item['collocations'], [])
        # 原句仍然带上：结果卡的 AI 按钮要用它组 prompt
        self.assertIn('committee', words[0]['context_sentence'])

    def test_prepare_local_is_not_capped_at_eight(self):
        """八条腿是同时踩词的能力，不是词数上限（§6 会分批，这里先不截）。"""
        candidates = [{'lemma': 'w%d' % i, 'surface': 'w%d' % i, 'meaning': '义'}
                      for i in range(24)]
        words, meta = LearningRouter().prepare_local('text', candidates, [], 'cet6', 20)
        self.assertEqual(len(words), 20)
        self.assertEqual(meta['eligible_count'], 24)

    def test_prepare_local_skips_mastered(self):
        words, _ = LearningRouter().prepare_local(
            'text', self.candidates,
            [{'word': 'accelerate', 'stage': 3, 'correct': 4, 'wrong': 0}], 'cet6', 8)
        self.assertEqual([w['lemma'] for w in words], ['thunder'])

    def test_select_still_supports_cloud_for_opt_in_callers(self):
        """契约兼容：`select()` 保留原行为给显式调用者（不会被我们删掉）。"""
        words, meta = LearningRouter(Provider()).select(
            'accelerated', self.candidates, [], 'cet6', 8)
        self.assertEqual(meta['source'], 'cloud')
        self.assertEqual(words[0]['context_meaning'], '加快')


class ContextRequestTests(unittest.TestCase):
    """§5.2/§5.3：AI 语境分析 = 用户点按钮才发，只发文本，输出要过校验。"""

    def setUp(self):
        self.item = {'lemma': 'accelerate', 'surface': 'accelerated',
                     'meaning': '加速；促进', 'level': 'CET6',
                     'context_sentence': 'The committee accelerated the plan.'}

    def test_request_body_is_text_only(self):
        from ai.context_request import build_request
        payload = build_request(self.item, '', 'zh')
        self.assertEqual(
            set(payload), {'word', 'lemma', 'dictionary_meaning', 'level',
                           'sentence', 'user_level', 'answer_language'})
        self.assertEqual(payload['sentence'], 'The committee accelerated the plan.')
        # 任何字段都不可能是二进制/图像数据
        self.assertTrue(all(isinstance(v, str) for v in payload.values()))

    def test_long_screen_text_is_truncated(self):
        from ai.context_request import MAX_SENTENCE_CHARS, build_request
        payload = build_request(self.item, 'x' * 50000, 'zh')
        self.assertEqual(len(payload['sentence']), MAX_SENTENCE_CHARS)

    def test_parse_accepts_good_json(self):
        from ai.context_request import parse_context
        ai = parse_context({'context_meaning': '加快（计划）', 'reason': '常考动词',
                            'collocations': ['accelerate growth', 42, '  '],
                            'examples': [{'sentence': 'We accelerated testing.',
                                          'meaning': '我们加快了测试。'},
                                         {'sentence': '   '}, '字符串不是对象']})
        self.assertEqual(ai['context_meaning'], '加快（计划）')
        self.assertEqual(ai['collocations'], ['accelerate growth'])
        self.assertEqual(len(ai['examples']), 1)
        self.assertEqual(ai['ai_source'], 'cloud')
        self.assertTrue(ai['ai_requested'])

    def test_parse_rejects_garbage(self):
        from ai.context_request import parse_context
        for bad in ({}, 'not json', {'context_meaning': ''},
                    {'context_meaning': '义', 'collocations': '不是数组'},
                    {'context_meaning': '义', 'examples': [{'sentence': 3}]}):
            with self.assertRaises(ValueError):
                parse_context(bad)

    def test_markdown_fenced_json_is_tolerated(self):
        from ai.context_request import parse_context
        ai = parse_context('```json\n{"context_meaning": "促进", "examples": []}\n```')
        self.assertEqual(ai['context_meaning'], '促进')

    def test_sync_core_uses_injected_transport(self):
        from ai.context_request import request_word_context
        seen = {}

        def transport(payload):
            seen.update(payload)
            return {'context_meaning': '加快', 'reason': '高频动词',
                    'collocations': ['accelerate the plan'],
                    'examples': [{'sentence': 'They accelerated the plan.',
                                  'meaning': '他们加快了计划。'}]}
        result = request_word_context(self.item, '', 'zh', transport=transport)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['ai']['context_meaning'], '加快')
        self.assertEqual(seen['word'], 'accelerated')
        # 校验失败必须整体降级，而不是显示半截内容
        self.assertEqual(request_word_context(
            self.item, '', 'zh', transport=lambda p: {'nope': 1})['status'], 'failed')

    def test_unconfigured_never_starts_a_thread(self):
        from PySide6.QtCore import QCoreApplication
        from ai.context_request import ContextRequest

        class NoConfig:
            def api_key(self): return ''
            def base_url(self): return ''
            def model(self): return ''
            def endpoint(self): return ''

        app = QCoreApplication.instance() or QCoreApplication([])
        request = ContextRequest(config=NoConfig())
        signals = []
        request.finished.connect(signals.append)
        self.assertFalse(request.start(self.item, 'sentence'))
        self.assertEqual(signals[0]['status'], 'unconfigured')
        self.assertIn('还没有配置', signals[0]['message'])
        self.assertIn('AI 设置', signals[0]['message'])
        self.assertEqual(signals[0]['missing'], ['API Key', 'Base URL', '模型名'])
        self.assertFalse(request.active)
        del app

    def test_dialog_button_renders_local_card_and_ai_result(self):
        """结果卡：本地先出释义，点了按钮才写 AI 内容；未配置时给明确提示。"""
        from PySide6.QtWidgets import QApplication
        import dialogs
        app = QApplication.instance() or QApplication([])
        items = [dict(self.item, ai_source='local', ai_requested=False,
                      ai_candidate_count=1, ai_eligible_count=1,
                      context_meaning=self.item['meaning'], ai_reason='',
                      collocations=[], screen_pos=(10, 10))]

        class Book:
            def stats(self): return {'today': 0, 'due': 0, 'total': 0}
            def has(self, word): return False
            def add(self, info): return True
            def remove(self, word): return False

        dialog = dialogs.WordResultDialog(None, items, Book(), 'CET6')
        ui = dialog._ai_ui['accelerate']
        # 默认状态下没有任何 AI 内容，也没有在途请求
        self.assertFalse(ui['box'].isVisible())
        self.assertEqual(ui['button'].text(), 'AI 语境分析与造句')
        self.assertEqual(dialog._ai_request, None)
        # 未配置 → 同步返回提示，不会起线程
        from ai.context_request import ContextRequest

        class NoConfig:
            def api_key(self): return ''
            def base_url(self): return ''
            def model(self): return ''
            def endpoint(self): return ''

        request = ContextRequest(config=NoConfig(), parent=dialog)
        dialog._ai_request = request
        dialog._ai_word = 'accelerate'
        request.finished.connect(
            lambda result: dialog._ai_finished('accelerate', result))
        request.start(items[0], 'sentence')
        self.assertIn('先配置 API/模型', ui['status'].text())
        self.assertEqual(ui['button'].text(), 'AI 语境分析与造句')
        # 成功结果只追加，不改词典释义与坐标
        dialog._ai_finished('accelerate', {
            'status': 'ok', 'elapsed': 1.5,
            'ai': {'context_meaning': '加快（计划）', 'ai_reason': '高频',
                   'collocations': ['accelerate the plan'],
                   'examples': [{'sentence': 'A.', 'meaning': '甲。'}],
                   'ai_source': 'cloud', 'ai_requested': True}})
        self.assertIn('加快（计划）', ui['labels']['context'].text())
        self.assertIn('accelerate the plan', ui['labels']['phrases'].text())
        self.assertEqual(items[0]['meaning'], '加速；促进')
        self.assertEqual(items[0]['screen_pos'], (10, 10))
        self.assertEqual(ui['button'].text(), '再分析一次')
        dialog.close()

    def test_worker_real_ocr_to_local_dictionary_and_coordinates(self):
        """真 OCR → 本地词典 → 屏幕坐标，**全程不许碰云端**（§5.1）。"""
        from PySide6.QtCore import QRect
        from PySide6.QtWidgets import QApplication
        from main import make_test_image
        from lexicon import Lexicon
        from pet_window import OcrWorker
        from wordbook import resource_path
        app = QApplication.instance() or QApplication([])
        dictionary = Lexicon(resource_path('assets', 'ecdict.sqlite'),
                             resource_path('assets', 'exam-tags.sqlite'))
        worker = OcrWorker(make_test_image(), dictionary, 'cet6', 8, True)
        worker.capture_rect = QRect(50, 60, 1180, 300)
        results = []
        worker.done.connect(lambda words, meta, error: results.append((words, meta, error)))
        # 就算机器上真的配了 key，默认链路也不能发出去 —— 
        # 用「调了就炸」的 provider 替换掉，任何云端入口都会被抓住。
        def explode(*args, **kwargs):
            raise AssertionError('OcrWorker 的默认链路里不允许调云端')
        with patch.dict(os.environ, {'LEXARA_AI_API_KEY': 'sk-should-never-be-used'}), \
                patch('ai.cloud_provider.CloudAIProvider.analyze', explode):
            worker.run()
        words, meta, error = results[0]
        self.assertFalse(error)
        self.assertTrue(words)
        self.assertEqual(meta['analysis']['source'], 'local')
        self.assertTrue(all(w.get('screen_pos') and w.get('ai_source') == 'local'
                            for w in words))
        self.assertTrue(all(not w.get('ai_requested') for w in words))
        self.assertTrue(all(w.get('meaning') for w in words))

if __name__ == '__main__':
    unittest.main()
