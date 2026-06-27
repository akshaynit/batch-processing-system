from app.domain.models import PromptItem
from app.interfaces.validation import ValidationContext
from app.services.validation.pipeline import ValidationPipeline
from app.services.validation.rules import (
    MaxPromptTokens,
    NonEmptyExternalId,
    NonEmptyPrompt,
    UniqueExternalId,
)


def make_pipeline() -> ValidationPipeline:
    return ValidationPipeline(
        [
            NonEmptyExternalId(),
            NonEmptyPrompt(min_chars=1),
            MaxPromptTokens(max_tokens=10),
            UniqueExternalId(),
        ]
    )


def test_valid_item_passes():
    ctx = ValidationContext()
    outcome = make_pipeline().validate_item(
        PromptItem(external_id="p-1", prompt="hello world"), ctx
    )
    assert outcome.ok
    assert outcome.errors == []


def test_empty_prompt_fails():
    ctx = ValidationContext()
    outcome = make_pipeline().validate_item(
        PromptItem(external_id="p-1", prompt="   "), ctx
    )
    assert not outcome.ok


def test_oversized_prompt_fails():
    ctx = ValidationContext()
    long_prompt = "x" * 1000  # ~250 tokens > max 10
    outcome = make_pipeline().validate_item(
        PromptItem(external_id="p-1", prompt=long_prompt), ctx
    )
    assert not outcome.ok


def test_duplicate_id_detected():
    ctx = ValidationContext()
    pipeline = make_pipeline()
    first = pipeline.validate_item(PromptItem(external_id="dup", prompt="hi"), ctx)
    second = pipeline.validate_item(PromptItem(external_id="dup", prompt="hi"), ctx)
    assert first.ok
    assert not second.ok
