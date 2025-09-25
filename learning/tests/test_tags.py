from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model

from learning.forms import VocabularyListForm
from learning.models import VocabularyList, Tag


User = get_user_model()


class VocabularyListTagFormTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username="teacher1",
            password="pass1234",
            first_name="Test",
            last_name="Teacher",
            is_teacher=True,
        )

    def test_form_creates_and_assigns_tags(self):
        form = VocabularyListForm(
            data={
                "name": "Animals",
                "source_language": "en",
                "target_language": "es",
                "tag_names": "animals, travel , animals",
            },
            teacher=self.teacher,
        )

        self.assertTrue(form.is_valid())
        vocab_list = form.save(commit=False)
        vocab_list.teacher = self.teacher
        vocab_list.save()
        form.save_tags(vocab_list)

        tag_names = set(vocab_list.tags.values_list("name", flat=True))
        self.assertSetEqual(tag_names, {"animals", "travel"})
        self.assertEqual(Tag.objects.filter(teacher=self.teacher).count(), 2)


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class VocabularyListTagFilterViewTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username="teacher2",
            password="pass1234",
            first_name="Another",
            last_name="Teacher",
            is_teacher=True,
        )
        self.client.force_login(self.teacher)

        self.list_one = VocabularyList.objects.create(
            name="Travel Basics",
            source_language="en",
            target_language="es",
            teacher=self.teacher,
        )
        self.list_two = VocabularyList.objects.create(
            name="Animal Friends",
            source_language="en",
            target_language="fr",
            teacher=self.teacher,
        )

        self.tag_travel = Tag.objects.create(name="travel", teacher=self.teacher)
        self.tag_animals = Tag.objects.create(name="animals", teacher=self.teacher)
        self.tag_easy = Tag.objects.create(name="easy", teacher=self.teacher)

        self.list_one.tags.add(self.tag_travel, self.tag_easy)
        self.list_two.tags.add(self.tag_animals, self.tag_easy)

    def test_filter_by_single_tag(self):
        response = self.client.get(
            reverse("teacher_dashboard"),
            {"tags": [self.tag_travel.id], "pane": "vocabulary"},
        )
        filtered = list(response.context["filtered_vocab_lists"])
        self.assertEqual(filtered, [self.list_one])
        self.assertEqual(response.context["selected_tag_ids"], [self.tag_travel.id])

    def test_filter_requires_all_selected_tags(self):
        response = self.client.get(
            reverse("teacher_dashboard"),
            {
                "tags": [self.tag_easy.id, self.tag_animals.id],
                "pane": "vocabulary",
            },
        )
        filtered = list(response.context["filtered_vocab_lists"])
        self.assertEqual(filtered, [self.list_two])

        # Ensure unfiltered list still contains all vocabulary lists
        all_lists = list(response.context["vocab_lists"])
        self.assertCountEqual(all_lists, [self.list_one, self.list_two])
