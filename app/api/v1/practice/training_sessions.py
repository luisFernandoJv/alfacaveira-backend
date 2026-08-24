# Trecho a colar em app/api/v1/practice/training_sessions.py
# (substitui só o corpo da função `answer_training_question`)

async def answer_training_question(
    session_id: uuid.UUID,
    question_id: uuid.UUID,
    body: AnswerSubmitRequest,
    current_user: CurrentUser,
    question_attempt_service: QuestionAttemptServiceDep,
) -> Envelope[AnswerResultResponse]:
    attempt = await question_attempt_service.submit_training_answer(
        user_id=current_user.id,
        session_id=session_id,
        question_id=question_id,
        data=body,
    )
    question = attempt.question
    return Envelope(
        data=AnswerResultResponse(
            question_id=attempt.question_id,
            selected_alternative_id=attempt.selected_alternative_id,
            correct_alternative_letter=question.correct_alternative_letter,
            is_correct=bool(attempt.is_correct),
            explanation=question.explanation,
            teacher_name=question.teacher_name,
        )
    )