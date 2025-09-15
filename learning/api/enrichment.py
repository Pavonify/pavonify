from __future__ import annotations

from typing import Any, Dict, List

from rest_framework import permissions, serializers, status, views
from rest_framework.response import Response

from learning.models import VocabularyWord
from learning.services.enrichment import get_enrichments

class PreviewRequestSerializer(serializers.Serializer):
    words = serializers.ListField(
        child=serializers.CharField(allow_blank=False, trim_whitespace=True),
        min_length=1, max_length=200
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
        words: List[str] = ser.validated_data["words"]
        data = get_enrichments(words)
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
            word = item["word"]
            vw, was_created = VocabularyWord.objects.get_or_create(
                list_id=list_id,
                defaults={"word": word},
                word=word,
            )
            if was_created:
                created += 1
            else:
                updated += 1

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
