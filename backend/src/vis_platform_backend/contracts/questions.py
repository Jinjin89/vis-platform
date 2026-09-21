from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from .common import StrictModel


class ClarificationChoice(StrictModel):
    choice_id: str = Field(default_factory=lambda: "choice_" + uuid4().hex)
    label: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=400)
    recommended: bool = False


class ClarificationQuestion(StrictModel):
    question_id: str = Field(default_factory=lambda: "question_" + uuid4().hex)
    header: str = Field(min_length=1, max_length=40)
    prompt: str = Field(min_length=1, max_length=1000)
    reason: str = Field(default="", max_length=600)
    selection: Literal["single", "multiple", "text"] = "single"
    choices: list[ClarificationChoice] = Field(default_factory=list, max_length=4)
    allow_free_text: bool = True

    @model_validator(mode="after")
    def validate_choices(self) -> ClarificationQuestion:
        if self.selection != "text" and len(self.choices) < 2:
            raise ValueError("choice questions require at least two options")
        if self.selection == "text" and (self.choices or not self.allow_free_text):
            raise ValueError("text questions require free text and no choices")
        if len({choice.choice_id for choice in self.choices}) != len(self.choices):
            raise ValueError("choice identifiers must be unique")
        if self.selection == "single" and sum(choice.recommended for choice in self.choices) > 1:
            raise ValueError("single-choice questions can recommend at most one option")
        return self


class PlannerQuestions(StrictModel):
    interaction_id: str = Field(default_factory=lambda: "interaction_" + uuid4().hex)
    questions: list[ClarificationQuestion] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def unique_questions(self) -> PlannerQuestions:
        if len({question.question_id for question in self.questions}) != len(self.questions):
            raise ValueError("question identifiers must be unique")
        return self


class ClarificationAnswer(StrictModel):
    question_id: str
    choice_ids: list[str] = Field(default_factory=list, max_length=4)
    free_text: str | None = Field(default=None, max_length=2000)


class PlannerAnswerRequest(StrictModel):
    project_id: str
    interaction_id: str
    answers: list[ClarificationAnswer] = Field(min_length=1, max_length=4)
