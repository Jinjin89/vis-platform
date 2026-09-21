from vis_platform_backend.contracts.questions import PlannerAnswerRequest, PlannerQuestions


class InvalidPlannerAnswer(ValueError):
    pass


def validate_answers(questions: PlannerQuestions, request: PlannerAnswerRequest) -> None:
    required = {question.question_id: question for question in questions.questions}
    supplied = [answer.question_id for answer in request.answers]
    if len(set(supplied)) != len(supplied) or set(supplied) != set(required):
        raise InvalidPlannerAnswer("Answer every question once before continuing.")
    for answer in request.answers:
        question = required[answer.question_id]
        if len(set(answer.choice_ids)) != len(answer.choice_ids):
            raise InvalidPlannerAnswer("The same choice cannot be selected twice.")
        if set(answer.choice_ids) - {choice.choice_id for choice in question.choices}:
            raise InvalidPlannerAnswer("The answer includes an unavailable choice.")
        text = (answer.free_text or "").strip()
        if text and not question.allow_free_text:
            raise InvalidPlannerAnswer("This question does not accept a custom answer.")
        if not answer.choice_ids and not text:
            raise InvalidPlannerAnswer("Choose an option or enter an answer.")
        if question.selection == "single" and len(answer.choice_ids) > 1:
            raise InvalidPlannerAnswer("Choose one option for this question.")
        if question.selection == "text" and answer.choice_ids:
            raise InvalidPlannerAnswer("This question requires a text answer.")
