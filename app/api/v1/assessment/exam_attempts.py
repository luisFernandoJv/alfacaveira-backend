# Trecho a colar em app/api/v1/assessment/exam_attempts.py
# (substitui só o corpo da função `answer_exam_question`)

async def answer_exam_question(
    attempt_id: uuid.UUID,
    question_id: uuid.UUID,
    body: AnswerSubmitRequest,
    current_user: CurrentUser,
    exam_attempt_service: ExamAttemptServiceDep,
) -> Envelope[AnswerResultResponse]:
    answer = await exam_attempt_service.submit_answer(
        user_id=current_user.id,
        attempt_id=attempt_id,
        question_id=question_id,
        data=body,
    )
    question = answer.question
    return Envelope(
        data=AnswerResultResponse(
            question_id=answer.question_id,
            selected_alternative_id=answer.selected_alternative_id,
            correct_alternative_letter=question.correct_alternative_letter,
            is_correct=bool(answer.is_correct),
            explanation=question.explanation,
            teacher_name=question.teacher_name,
        )
    )