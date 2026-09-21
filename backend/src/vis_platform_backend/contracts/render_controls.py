from typing import Annotated, Literal

from pydantic import Field

from .parameters import BooleanControl, ChoiceControl, NumberControl, TextControl


class RenderNumberControl(NumberControl):
    update_strategy: Literal["rerun"] = "rerun"


class RenderChoiceControl(ChoiceControl):
    update_strategy: Literal["rerun"] = "rerun"


class RenderTextControl(TextControl):
    update_strategy: Literal["rerun"] = "rerun"


class RenderBooleanControl(BooleanControl):
    update_strategy: Literal["rerun"] = "rerun"


RenderControl = Annotated[
    RenderNumberControl | RenderChoiceControl | RenderTextControl | RenderBooleanControl,
    Field(discriminator="type"),
]
