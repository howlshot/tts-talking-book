"""Tests that run without a speech model. The end-to-end test swaps Kokoro for
tone bursts, then runs the same validator the real build uses.

    python -m unittest discover tests
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

from talkingbook import dtb
from talkingbook.asr import wer, words
from talkingbook.audio import CLIP_LEAD, CLIP_TAIL, Track, trim
from talkingbook.source import build_divisions, clean
from talkingbook.speech import SAMPLE_RATE, Lexicon, sentences, speakable_heading

TOOLS = all(shutil.which(t) for t in ("ffmpeg", "ffprobe", "xmllint"))


class Text(unittest.TestCase):
    def test_clean_closes_space_before_punctuation(self):
        self.assertEqual(clean("<b>Section 1</b> . All"), "Section 1. All")

    def test_divisions(self):
        blocks = [("h1", "THE CONSTITUTION"), ("p", "We the People."), ("h2", "Article I."), ("p", "Section 1. All powers."), ("p", "More text."), ("p", "Section. 2. The House.")]
        title, divs = build_divisions(blocks)
        self.assertEqual(title, "THE CONSTITUTION")
        self.assertEqual([d.cls for d in divs], ["prelimitem", "chapter"])
        self.assertEqual([c.heading for c in divs[1].children], ["Section 1", "Section 2"])
        self.assertEqual(divs[1].children[0].paragraphs, ["All powers.", "More text."])

    def test_display_headings_keep_roman_numerals(self):
        from talkingbook.build import display_heading

        self.assertEqual(display_heading("ARTICLE III"), "Article III")
        self.assertEqual(display_heading("Section 2"), "Section 2")

    def test_spoken_headings_avoid_roman_numerals(self):
        self.assertEqual(speakable_heading("Article IV"), "Article 4")
        self.assertEqual(speakable_heading("Section 2"), "Section 2")

    def test_sentences_merge_short_fragments(self):
        self.assertEqual(sentences("No. It is so. The rest of this sentence is long enough to stand alone."), ["No. It is so. The rest of this sentence is long enough to stand alone."])

    def test_lexicon_logs_every_hit(self):
        lex = Lexicon.load(Path(__file__).parents[1] / "sources/constitution.lexicon.json")
        log: list = []
        self.assertEqual(lex.apply("Wm. Few, Thos. Mifflin", log), "William Few, Thomas Mifflin")
        self.assertEqual([h["said"] for h in log], ["William", "Thomas"])


class Audio(unittest.TestCase):
    def test_trim(self):
        tone = np.full(2400, 0.5, dtype=np.float32)
        quiet = np.zeros(2400, dtype=np.float32)
        self.assertEqual(len(trim(np.concatenate([quiet, tone, quiet]), SAMPLE_RATE)), 2400)

    def test_clip_marks_sit_inside_the_silence(self):
        t = Track(SAMPLE_RATE)
        clip = t.add(np.ones(SAMPLE_RATE, dtype=np.float32), 0.3, 0.6)
        self.assertAlmostEqual(clip.speech_start - clip.begin, CLIP_LEAD, places=3)
        self.assertAlmostEqual(clip.end - clip.speech_end, CLIP_TAIL, places=3)
        self.assertAlmostEqual(t.seconds, 1.9, places=3)

    def test_pads_too_short_for_the_clip_rule_are_refused(self):
        with self.assertRaises(AssertionError):
            Track(SAMPLE_RATE).add(np.ones(10, dtype=np.float32), 0.1, 0.6)

    def test_clock(self):
        self.assertEqual(dtb.clock(3723.4567), "1:02:03.457")


class Scoring(unittest.TestCase):
    def test_words_normalize_numbers_and_numerals(self):
        self.assertEqual(words("Article III, Section two."), ["article", "3", "section", "2"])
        self.assertEqual(words("I am"), ["i", "am"])

    def test_wer(self):
        self.assertEqual(wer(["a", "b", "c"], ["a", "x", "c", "d"]), (2, 3))


def tiny_epub(path: Path) -> None:
    chapter = "<html><body><h1>A Small Book</h1><p>This is the opening note for the reader.</p><h2>Chapter I</h2><p>Section 1. The first part has one sentence. It also has a second one.</p><p>Section 2. The second part is here.</p><h2>Chapter II</h2><p>The last chapter is short.</p></body></html>"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles></container>')
        z.writestr("OEBPS/book.opf", '<package><manifest><item id="c1" href="c1.html"/></manifest><spine><itemref idref="c1"/></spine></package>')
        z.writestr("OEBPS/c1.html", chapter)


def tones(text: str) -> np.ndarray:
    """Stand-in voice: a 220 Hz tone, 60 ms per word."""
    n = int(SAMPLE_RATE * 0.06 * max(1, len(text.split())))
    return (0.3 * np.sin(2 * np.pi * 220 * np.arange(n) / SAMPLE_RATE)).astype(np.float32)


tones.name = "test tones"


@unittest.skipUnless(TOOLS, "needs ffmpeg and xmllint")
class EndToEnd(unittest.TestCase):
    def test_build_passes_every_check(self):
        from talkingbook.build import Builder
        from talkingbook.validate import validate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tiny_epub(root / "book.epub")
            config = {"pid": "tst000001", "uid": "sample-tst000001", "source": "book.epub", "author": "Test Author", "author_phrase": "by", "spoken_author": "Test Author"}
            report = Builder(config, root, root / "build", tones, "none").run()
            result = validate(root / "build", "tst000001")
            failed = [c for c in result.checks if not c["ok"]]
            self.assertEqual(failed, [])
            plan = json.loads((root / "build/plan.json").read_text())
            self.assertEqual([n["cls"] for n in plan["nav"]], ["title/author", "prelimitem", "chapter", "chapter", "close"])
            self.assertEqual([c["label"] for c in plan["nav"][2]["children"]], ["Section 1", "Section 2"])
            self.assertEqual(report["files"][:3], ["dtbsmil-2005-1.dtd", "ncx-2005-1.dtd", "oeb12.ent"])


if __name__ == "__main__":
    unittest.main()
