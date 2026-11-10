import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("content_factory", ROOT / "scripts" / "content_factory.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ContentFactoryTests(unittest.TestCase):
    def test_arabic_normalization(self):
        self.assertEqual(MODULE.normalize("إختبارٌ مُهمّ!"), MODULE.normalize("اختبار مهم"))

    def test_subtitle_word_count(self):
        self.assertEqual(MODULE.subtitle_word_count("لغز لم يحل بعد"), 4)

    def test_scene_duration_bounds_are_enforced(self):
        channel = {"id": "science"}
        pipeline = {
            "video": {"min_seconds": 45, "max_seconds": 58, "scene_change_seconds_min": 2.2,
                      "scene_change_seconds_max": 2.8, "subtitle_words_min": 1, "subtitle_words_max": 3},
            "quality_gates": {"require_source_review": True}
        }
        source = {"duration_seconds": 50, "editorial_status": "approved", "rights_status": "approved",
                  "original_script": True, "title": "عنوان", "sources": [{"title": "مرجع", "url": "https://x.test",
                  "review_status": "verified"}], "scenes": [{"duration_seconds": 2.0, "narration": "نص",
                  "subtitle": "عنوان قصير", "visual_prompt": "لقطة"}]}
        errors = MODULE.validate_package(source, channel, pipeline, {"ideas": []})
        self.assertTrue(any("scene #1" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
