from __future__ import annotations

from typing import Any, Dict, List, Optional

from django.db import DataError, transaction
from django.shortcuts import get_object_or_404

from rest_framework import permissions, serializers, status, views
from rest_framework.response import Response

from learning.models import VocabularyList, VocabularyWord
from learning.services.enrichment import get_enrichments


# ---------------------- Serializers ----------------------

class PreviewEntrySerializer(serializers.Serializer):
    word = serializers.CharField(allow_blank=False, trim_whitespace=True, max_length=100)
    translation = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True, max_length=100)
    fact_type = serializers.ChoiceField(choices=("etymology", "idiom", "trivia"), required=False)
    exclude_images = serializers.ListField(
        child=serializers.URLField(),
        required=False,
        allow_empty=True,
        max_length=50,
    )


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


# ---------------------- Helpers ----------------------

def _truncate_for_field(instance: VocabularyWord, field_name: str, value: Optional[str]) -> Optional[str]:
    """Trim string to the DB max_length for the given model field."""
    if value is None:
        return None
    val = str(value)
    try:
        field = instance._meta.get_field(field_name)
        max_len = getattr(field, "max_length", None)
        if max_len and len(val) > max_len:
            return val[:max_len]
        return val
    except Exception:
        # If something odd happens, still prevent overflows with a safe cap.
        return val[:200] if len(val) > 200 else val


def _set_if_changed(instance: VocabularyWord, field_name: str, new_value: Any) -> None:
    """Assign only when different, to reduce writes."""
    if getattr(instance, field_name) != new_value:
        setattr(instance, field_name, new_value)


# ---------------------- Views ----------------------

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

        # One transaction keeps things consistent but still lets us count created/updated
        with transaction.atomic():
            for item in items:
                # Basic strings (trim early)
                word = (item.get("word") or "").strip()
                if not word:
                    continue
                translation = (item.get("translation") or "").strip()

                # Upsert by (list_id, word)
                vw, was_created = VocabularyWord.objects.get_or_create(
                    list_id=list_id,
                    word=word,
                    defaults={"translation": translation},
                )

                # Ensure word/translation respect DB limits
                safe_word = _truncate_for_field(vw, "word", word)
                if safe_word != vw.word:
                    _set_if_changed(vw, "word", safe_word)

                if was_created:
                    created += 1
                    if translation:
                        _set_if_changed(vw, "translation", _truncate_for_field(vw, "translation", translation))
                else:
                    updated += 1
                    if translation and translation != (vw.translation or ""):
                        _set_if_changed(vw, "translation", _truncate_for_field(vw, "translation", translation))

                # Image
                if item.get("approveImage") and item.get("image"):
                    img = item["image"] or {}
                    url = _truncate_for_field(vw, "image_url", img.get("url"))
                    thumb = _truncate_for_field(vw, "image_thumb_url", img.get("thumb") or img.get("url"))
                    source = _truncate_for_field(vw, "image_source", img.get("source") or "Wikimedia")
                    attribution = _truncate_for_field(vw, "image_attribution", img.get("attribution") or "")
                    license_text = _truncate_for_field(vw, "image_license", img.get("license") or "")

                    _set_if_changed(vw, "image_url", url)
                    _set_if_changed(vw, "image_thumb_url", thumb)
                    _set_if_changed(vw, "image_source", source)
                    _set_if_changed(vw, "image_attribution", attribution)
                    _set_if_changed(vw, "image_license", license_text)
                    _set_if_changed(vw, "image_approved", True)

                # Fact
                if item.get("approveFact") and item.get("fact"):
                    fact = item["fact"] or {}
                    # Truncate text to DB column max_length (serializer already caps at 220)
                    fact_text = _truncate_for_field(vw, "word_fact_text", fact.get("text") or "")
                    fact_type = (fact.get("type") or "trivia")
                    # Ensure type fits column too
                    fact_type = _truncate_for_field(vw, "word_fact_type", fact_type) or "trivia"
                    try:
                        conf = float(fact.get("confidence") or 0.0)
                    except (TypeError, ValueError):
                        conf = 0.0

                    _set_if_changed(vw, "word_fact_text", fact_text)
                    _set_if_changed(vw, "word_fact_type", fact_type)
                    _set_if_changed(vw, "word_fact_confidence", conf)
                    _set_if_changed(vw, "word_fact_approved", True)

                # Final save with robust error handling
                try:
                    vw.save()
                except DataError as e:
                    # Surface a useful error instead of 500s
                    return Response(
                        {
                            "detail": "One or more fields exceeded database length limits.",
                            "word": word,
                            "error": str(e),
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        return Response({"created": created, "updated": updated}, status=status.HTTP_200_OK)
