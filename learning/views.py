import json
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

# Map language codes to full names
LANGUAGE_MAP = {
    'en': 'English',
    'de': 'German',
    'fr': 'French',
    'sp': 'Spanish',
    'it': 'Italian',
}

@login_required
def reading_lab(request):
    if request.method == "POST":
        # Ensure the user is a teacher and has AI credits
        if not request.user.is_teacher or request.user.ai_credits <= 0:
            return render(request, "error.html", {"message": "You do not have enough AI credits or are not a teacher."})

        # Get form data
        vocabulary_list_id = request.POST.get("vocabulary_list")
        selected_word_ids = request.POST.getlist("selected_words")
        exam_board = request.POST.get("exam_board")
        topic = request.POST.get("topic")
        custom_topic = request.POST.get("custom_topic")
        if custom_topic:
            topic = custom_topic
        level = request.POST.get("level")
        word_count = int(request.POST.get("word_count", 100))
        tenses = request.POST.getlist("tenses")

        # Fetch selected vocabulary list and words
        vocabulary_list = VocabularyList.objects.get(id=vocabulary_list_id)
        selected_words = VocabularyWord.objects.filter(id__in=selected_word_ids)

        # Prepare language names from codes
        source_lang_code = vocabulary_list.source_language  # e.g., 'en'
        target_lang_code = vocabulary_list.target_language  # e.g., 'de'
        source_lang_name = LANGUAGE_MAP.get(source_lang_code, 'Unknown')
        target_lang_name = LANGUAGE_MAP.get(target_lang_code, 'Unknown')

        # Create a string of vocabulary pairs: "easy = einfach, happy = glücklich, ..."
        selected_pairs = ", ".join([f"{w.word} = {w.translation}" for w in selected_words])

        # Build the initial prompt
        prompt = (
            f"Generate a parallel text in {source_lang_name} and {target_lang_name} "
            f"on the topic of {topic}. The text should be at {level} level. "
            f"The word count should be approximately {word_count} words."
        )
        if tenses:
            prompt += f" The text should be written in the following tense(s): {', '.join(tenses)}."

        # Instruct the model to use the provided vocabulary pairs exactly.
        prompt += (
            f" Here are the vocabulary pairs: {selected_pairs}. "
            f"In the {source_lang_name} text, incorporate the source words exactly as given. "
            f"In the {target_lang_name} text, incorporate the provided translations exactly. "
            "Do not provide any alternative translations."
        )
        prompt += " Separate the source and target texts with '==='."

        # Call Gemini API using the appropriate model name
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)
        generated_text = response.text

        # Debug output
        print("Generated Text:", generated_text)

        # Split the generated text using the custom delimiter
        text_parts = generated_text.split("===")
        if len(text_parts) < 2:
            return render(request, "error.html", {"message": "The generated text is not in the expected format."})

        source_text, target_text = text_parts[0].strip(), text_parts[1].strip()

        # Save the generated texts to the database
        reading_lab_text = ReadingLabText(
            teacher=request.user,
            vocabulary_list=vocabulary_list,
            exam_board=exam_board,
            topic=topic,
            level=level,
            word_count=word_count,
            generated_text_source=source_text,
            generated_text_target=target_text,
        )
        reading_lab_text.save()
        reading_lab_text.selected_words.set(selected_words)

        # Deduct 1 AI credit from the teacher
        request.user.deduct_credit()

        return redirect("reading_lab_display", reading_lab_text.id)

    # For GET requests, display the form
    exam_board_topics_json = json.dumps(EXAM_BOARD_TOPICS)
    vocabulary_lists = VocabularyList.objects.filter(teacher=request.user)
    return render(request, "learning/reading_lab.html", {
        "vocabulary_lists": vocabulary_lists,
        "exam_boards": list(EXAM_BOARD_TOPICS.keys()),
        "exam_board_topics_json": exam_board_topics_json
    })
