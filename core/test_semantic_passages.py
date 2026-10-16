"""Passage vectors for long notes.

Uses the mocked OpenAI of core.test_semantic_search: its fake model maps words
to concept axes. The long Garden note below is mostly garden words, so its
whole vector sits far from "sign-in failure"; one passage holds the sentence
about a sign-in error and lands close to it.
"""

from unittest import mock


from core.models import Projects, SessionPassageEmbedding, Sessions
from core.services import semantic_search
from core.services.semantic_search import (
    PASSAGE_CHARS,
    min_similarity,
    session_scores,
    split_passages,
)
from core.test_semantic_search import FakeOpenAI, SemanticSearchTestCase, fake_vector

LONG_NOTE = (
    "Watered the plants along the south bed and checked the drip lines. "
    "Pruned the orchard rows, raked the leaves and stacked the cuttings. "
    "Moved the garden hose and set out the new seedlings by the fence. "
    "Then a long tea break on the porch. "
    "Answered a call about a sign-in error on the farm shop website. "
    "Packed up the van afterwards."
)


class SplitPassagesTests(SemanticSearchTestCase):
    def test_a_note_that_fits_one_passage_has_none(self):
        self.assertEqual(split_passages(""), [])
        self.assertEqual(split_passages("Watered the plants."), [])
        self.assertEqual(split_passages("x " * (PASSAGE_CHARS // 2 - 1)), [])

    def test_sentences_are_grouped_and_each_passage_repeats_the_last_sentence(self):
        passages = split_passages(LONG_NOTE)
        self.assertEqual(len(passages), 2)
        self.assertTrue(all(len(passage) <= PASSAGE_CHARS for passage in passages))
        self.assertTrue(passages[0].endswith("Then a long tea break on the porch."))
        self.assertTrue(passages[1].startswith("Then a long tea break on the porch."))
        self.assertIn("sign-in error", passages[1])
        self.assertNotIn("orchard", passages[1])


    def test_overlong_sentences_and_words_are_cut(self):
        words = split_passages(" ".join(["word"] * 200))
        self.assertGreater(len(words), 1)
        self.assertTrue(all(len(passage) <= PASSAGE_CHARS for passage in words))
        blob = split_passages("x" * (PASSAGE_CHARS * 3))
        self.assertEqual([len(passage) for passage in blob], [PASSAGE_CHARS] * 3)


class PassageSyncTests(SemanticSearchTestCase):
    def setUp(self):
        super().setUp()
        self.long = self._session(self.garden, LONG_NOTE, days_ago=5)

    def _passages(self, session):
        return list(
            SessionPassageEmbedding.objects.filter(session=session).order_by("position")
        )

    def test_only_long_notes_get_passages(self):
        self._sync()
        self.assertEqual(len(self._passages(self.long)), 2)
        self.assertEqual(
            SessionPassageEmbedding.objects.exclude(session=self.long).count(), 0
        )
        # Each passage is embedded with its project as context.
        inputs = [text for batch in FakeOpenAI.all_inputs() for text in batch]
        self.assertIn("Garden\n" + split_passages(LONG_NOTE)[1], inputs)


    def test_an_edit_replaces_the_passages_and_shortening_removes_them(self):
        self._sync()
        Sessions.objects.filter(pk=self.long.pk).update(note=LONG_NOTE + " " + LONG_NOTE)
        self._sync()
        expected = len(split_passages(LONG_NOTE + " " + LONG_NOTE))
        self.assertGreater(expected, 2)
        self.assertEqual([p.position for p in self._passages(self.long)], list(range(expected)))
        Sessions.objects.filter(pk=self.long.pk).update(note="Watered the plants.")
        self._sync()
        self.assertEqual(self._passages(self.long), [])

    def test_a_batch_embedded_from_old_text_is_not_written(self):
        # The note changes while its passages are at the provider.
        original = FakeOpenAI._create

        def edit_mid_call(client, **kwargs):
            if any(text.startswith("Garden\nThen a long tea break") for text in kwargs["input"]):
                Sessions.objects.filter(pk=self.long.pk).update(note=LONG_NOTE + " Locked the shed.")
            return original(client, **kwargs)

        with mock.patch.object(FakeOpenAI, "_create", edit_mid_call):
            self._sync()
        self.assertEqual(self._passages(self.long), [])
        # The next sync embeds the current text.
        self._sync()
        passages = self._passages(self.long)
        self.assertEqual(len(passages), len(split_passages(LONG_NOTE + " Locked the shed.")))
        inputs = [text for batch in FakeOpenAI.all_inputs() for text in batch]
        self.assertTrue(any(text.endswith("Locked the shed.") for text in inputs))


class PassageSearchTests(SemanticSearchTestCase):
    def setUp(self):
        super().setUp()
        self.long = self._session(self.garden, LONG_NOTE, days_ago=5)
        self._sync()


    def test_a_buried_sentence_finds_its_session(self):
        self.assertIn(self.long.pk, self._related("sign-in failure"))
        SessionPassageEmbedding.objects.all().delete()
        self.assertNotIn(self.long.pk, self._related("sign-in failure"))

    def test_the_best_passage_sets_the_score(self):
        sessions = Sessions.objects.filter(user=self.user)
        query = semantic_search.decode_vector(
            semantic_search.encode_vector(fake_vector("sign-in failure"))
        )
        scores = session_scores(self.user, sessions, query, cutoff=-1.0)
        self.assertGreater(scores[self.long.pk], 0.7)
        self.assertLess(scores[self.plants.pk], min_similarity())
        whole = session_scores(self.user, sessions, query, cutoff=-1.0, passages=False)
        self.assertLess(whole[self.long.pk], min_similarity())


    def test_stale_passages_are_not_used(self):
        Sessions.objects.filter(pk=self.long.pk).update(note=LONG_NOTE.replace("van", "truck"))
        self.assertNotIn(self.long.pk, self._related("sign-in failure"))
        self._sync()
        self.assertIn(self.long.pk, self._related("sign-in failure"))


    def test_a_project_is_related_through_a_passage(self):
        self.assertIn(self.garden.pk, self._related_projects("sign-in failure"))

    def test_other_accounts_passages_never_appear(self):
        other = self._user("semantic-passages-other", "other-key")
        foreign_project = Projects.objects.create(user=other, name="Garden")
        foreign = self._session(foreign_project, LONG_NOTE, user=other)
        self._sync()
        self.assertTrue(SessionPassageEmbedding.objects.filter(session=foreign).exists())
        self.assertNotIn(foreign.pk, self._related("sign-in failure"))
