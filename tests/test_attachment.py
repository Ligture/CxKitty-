"""Replay chapter-card responses without login, OCR, or real network requests."""

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


def load_base():
    root = Path(__file__).resolve().parents[1]
    package = types.ModuleType("_attachment_test")
    package.__path__ = [str(root / "cxapi")]
    logger = types.ModuleType("core.logger")
    logger.Logger = mock.Mock
    schema = types.ModuleType("_attachment_test.schema")
    schema.QuestionModel = schema.QuestionsExportSchema = dict
    session = types.ModuleType("_attachment_test.session")
    session.SessionWraper = mock.Mock
    modules = {
        "_attachment_test": package,
        "core": types.ModuleType("core"),
        "core.logger": logger,
        "_attachment_test.schema": schema,
        "_attachment_test.session": session,
    }
    with mock.patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location("_attachment_test.base", root / "cxapi/base.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


base = load_base()


class AttachmentTests(unittest.TestCase):
    def fetch(self, html):
        response = mock.Mock(text=html, url="https://mooc1-api.chaoxing.com/knowledge/cards?token=secret")
        session = mock.Mock()
        session.get.return_value = response
        task = base.TaskPointBase(session, 0, 1, 2, 3, 4)
        task.logger = mock.Mock()
        task.fetch_attachment()
        response.raise_for_status.assert_called_once()
        return task.attachment

    def test_original_page(self):
        self.assertEqual(self.fetch('<head><script type="text/javascript">window.AttachmentSetting = {"attachments": []};</script></head>'), {"attachments": []})

    def test_data_in_later_script(self):
        self.assertEqual(self.fetch('<head><script type="text/javascript">var x = 1;</script><script>window.AttachmentSetting={"attachments": []};</script></head>'), {"attachments": []})

    def test_multiline_body_script_without_semicolon(self):
        self.assertEqual(self.fetch('<body><script>window.AttachmentSetting =\n{\n"attachments": []\n}\n</script></body>'), {"attachments": []})

    def test_following_javascript_and_semicolon_in_string(self):
        payload = {"title": "a; } b", "attachments": []}
        self.assertEqual(self.fetch('<head><script type="text/javascript">window.AttachmentSetting = ' + json.dumps(payload) + '; var other = {};</script></head>'), payload)

    def test_unopened_chapter(self):
        with self.assertRaises(base.ChapterNotOpened):
            self.fetch('<body><p class="blankTips"> \n章节未开放！ </p></body>')

    def test_server_message(self):
        with self.assertRaisesRegex(base.APIError, "无权限访问"):
            self.fetch('<body><p class="blankTips">无权限访问</p></body>')

    def test_unrecognized_page_has_context_without_query_secrets(self):
        with self.assertRaises(base.APIError) as caught:
            self.fetch('<head><title>请登录</title><script type="text/javascript">var x=1;</script></head>')
        message = str(caught.exception)
        self.assertIn("AttachmentSetting", message)
        self.assertIn("请登录", message)
        self.assertIn("knowledgeid=3", message)
        self.assertNotIn("secret", message)

    def test_empty_page_has_actionable_error(self):
        with self.assertRaisesRegex(base.APIError, "AttachmentSetting"):
            self.fetch("")

    def test_malformed_or_wrong_type_data(self):
        for payload in ('{"attachments":', 'null', '[]', '"text"'):
            with self.subTest(payload=payload), self.assertRaises(base.APIError):
                self.fetch('<head><script type="text/javascript">window.AttachmentSetting=' + payload + ';</script></head>')


if __name__ == "__main__":
    unittest.main()
