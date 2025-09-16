from __future__ import annotations

from typing import Any, Dict, List

from rest_framework import permissions, serializers, status, views
from rest_framework.response import Response

from django.shortcuts import get_object_or_404

from learning.models import VocabularyList, VocabularyWord
from learning.services.enrichment import get_enrichments

class PreviewEntrySerializer(serializers.Serializer):
    word = serializers.CharField(allow_blank=False, trim_whitespace=True, max_length=100)
    translation = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True, max_length=100)
    fact_type = serializers.ChoiceField(choices=("etymology", "idiom", "trivia"), required=False)


class PreviewRequestSerializer(serializers.Serializer):
    list_id = serializers.IntegerField()
    entries = serializers.ListField(
        child=PreviewEntrySerializer(),
        min_length=1,
        max_length=200,
    )

class ImagePayloadSerializer(serializers.Serializer):
    url = serializers.URLField()
    thumb = serializers.URLField(required=False, allow_blank=True)
    source = serializers.CharField(required=False, allow_blank=True)
    attribution = serializers.CharField(required=False, allow_blank=True)
    license = serializers.CharField(required=False, allow_blank=True)

class FactPayloadSerializer(serializers.Serializer):
    text = serializers.CharField(allow_blank=True, max_length=220)
    type = serializers.ChoiceField(choices=("etymology", "idiom", "trivia"))
    confidence = serializers.FloatField(required=False)

class ConfirmItemSerializer(serializers.Serializer):
    word = serializers.CharField()
    translation = serializers.CharField(required=False, allow_blank=True)
    image = ImagePayloadSerializer(required=False)
    fact = FactPayloadSerializer(required=False)
    approveImage = serializers.BooleanField(default=False)
    approveFact = serializers.BooleanField(default=False)

class ConfirmRequestSerializer(serializers.Serializer):
    list_id = serializers.IntegerField()
    items = serializers.ListField(child=ConfirmItemSerializer(), min_length=1)

class EnrichmentPreviewAPI(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        ser = PreviewRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        list_id: int = ser.validated_data["list_id"]
        entries: List[Dict[str, Any]] = ser.validated_data["entries"]

        vocab_list = get_object_or_404(VocabularyList, id=list_id, teacher=request.user)

        data = get_enrichments(
            entries,
            source_language=vocab_list.source_language,
            target_language=vocab_list.target_language,
        )
        return Response(data, status=status.HTTP_200_OK)

class EnrichmentConfirmAPI(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        ser = ConfirmRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        list_id = ser.validated_data["list_id"]
        items: List[Dict[str, Any]] = ser.validated_data["items"]

        created = 0
        updated = 0
        for item in items:
            word = (item.get("word") or "").strip()
            if not word:
                continue
            translation = (item.get("translation") or "").strip()
            vw, was_created = VocabularyWord.objects.get_or_create(
                list_id=list_id,
                word=word,
                defaults={"translation": translation},
            )
            if was_created:
                if translation:
                    vw.translation = translation
                created += 1
            else:
                updated += 1
                if translation and translation != (vw.translation or ""):
                    vw.translation = translation
            if word != (vw.word or ""):
                vw.word = word

            if item.get("approveImage") and item.get("image"):
                img = item["image"]
                vw.image_url = img.get("url")
                vw.image_thumb_url = img.get("thumb") or img.get("url")
                vw.image_source = img.get("source") or "Wikimedia"
                vw.image_attribution = img.get("attribution") or ""
                vw.image_license = img.get("license") or ""
                vw.image_approved = True

            if item.get("approveFact") and item.get("fact"):
                fact = item["fact"]
                vw.word_fact_text = fact.get("text") or ""
                vw.word_fact_type = fact.get("type") or "trivia"
                vw.word_fact_confidence = fact.get("confidence") or 0.0
                vw.word_fact_approved = True

            vw.save()

        return Response({"created": created, "updated": updated}, status=status.HTTP_200_OK)
