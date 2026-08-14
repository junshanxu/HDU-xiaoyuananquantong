import io
import threading
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

import xy_auto as xy


def make_cfg(**overrides):
    values = {
        "course_type": "1",
        "user_id": "",
        "college_id": "",
        "ah": "",
        "retry_exam": False,
        "max_exam_retry": 1,
        "exam_class": "10",
        "cancel_event": threading.Event(),
        "delay": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class PhaseOneTests(unittest.TestCase):
    def test_completed_course_skips_directory_request(self):
        session = object()
        cfg = make_cfg()
        courses = {
            "code": 200,
            "data": [
                {"id": "done", "name": "已完成课程", "isFinsh": True},
                {"id": "todo", "name": "未完成课程", "isFinsh": False},
            ],
        }
        directory = {
            "code": 200,
            "data": [{"list": [
                {"id": "article-done", "course": "已完成文章", "isFinsh": True},
                {"id": "article-todo", "course": "未完成文章", "isFinsh": False},
            ]}],
        }
        output = io.StringIO()

        with mock.patch.object(xy, "api_course_list", return_value=courses), \
                mock.patch.object(xy, "api_directory_list", return_value=directory) as directory_call, \
                mock.patch.object(xy, "do_article", return_value=True) as article_call, \
                mock.patch.object(xy, "_pause"):
            with redirect_stdout(output):
                result = xy.run_courses(session, cfg, {})

        directory_call.assert_called_once_with(session, cfg, "todo")
        article_call.assert_called_once_with(session, cfg, {}, "article-todo", "未完成文章")
        self.assertEqual(result, (1, 1, 0))
        self.assertIn("跳过课程 1", output.getvalue())

    def test_exam_reuses_prefetched_test_info(self):
        cfg = make_cfg(user_id="123456", ah="abcdefgh")
        question = {
            "id": "q1",
            "question": "测试题",
            "quesType": "单选",
            "optionA": "选项 A",
        }
        test_info = {
            "code": 200,
            "data": {"id": "exam-1", "name": "正式考试", "lastNum": 1},
        }

        with mock.patch.object(xy, "api_test_get_test", side_effect=AssertionError("重复查询考试状态")), \
                mock.patch.object(xy, "api_test_create", return_value={"code": 200, "data": {"logId": "log-1"}}), \
                mock.patch.object(xy, "api_test_list", return_value={"code": 200, "data": {"data": [{"question": question}]}}), \
                mock.patch.object(xy, "api_imitate_test", return_value={
                    "code": 200,
                    "data": {"isSuccess": True, "count": 100, "num": 0, "certificate": "cert-1"},
                }), \
                mock.patch.object(xy, "load_certificate_image", return_value=False):
            result = xy.do_exam(
                object(), cfg, {"测试题": {"answer": "A"}}, "2", test_info=test_info
            )

        self.assertTrue(result)
        self.assertEqual(cfg.certificate_id, "cert-1")

    def test_request_stats_are_grouped_without_url_parameters(self):
        session = xy.Session()
        session.timings = [
            {"path": "/wap/test/getTest", "status": "ok", "elapsed_ms": 120.0},
            {"path": "/wap/test/getTest", "status": "ok", "elapsed_ms": 80.0},
            {"path": "/wap/test/create", "status": "http_500", "elapsed_ms": 40.0},
        ]

        result = xy.format_request_stats(session, wall_elapsed_ms=300.0)

        self.assertIn("请求统计：3 次", result)
        self.assertIn("/wap/test/getTest: 2 次", result)
        self.assertIn("/wap/test/create: 1 次", result)
        self.assertIn("异常 1 次", result)
        self.assertNotIn("ah=", result)


if __name__ == "__main__":
    unittest.main()
