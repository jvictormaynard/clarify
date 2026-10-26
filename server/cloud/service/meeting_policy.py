"""Fixed meeting operations; dictation and selected-text policy stay separate."""

from pathlib import Path

from shared.meeting_contract import (
    SUMMARY_INSTRUCTION,
    MAX_SOURCE_BYTES,
    MAX_TRANSCRIPT_BYTES,
    MANAGED_ASR_MODEL,
    MANAGED_NOTES_MODEL,
)
from . import groq, ledger
from .funding import money


def transcribe(path, duration_ms, language, operation):
    cost = ledger.asr_cost(duration_ms)
    ledger.authorize(operation, cost)
    fields = {
        "model": MANAGED_ASR_MODEL,
        "response_format": "json",
        "temperature": "0",
    }
    if language != "auto":
        fields["language"] = language
    with Path(path).open("rb") as stream:
        answer = groq.perform(
            "audio/transcriptions",
            data=fields,
            files={"file": ("meeting.wav", stream, "audio/wav")},
        )
    transcript = answer.get("text")
    if (
        not isinstance(transcript, str)
        or len(transcript.encode()) > MAX_TRANSCRIPT_BYTES
    ):
        raise groq.ProviderFailure(cost=cost)
    # A silent valid chunk is committed as an empty transcript. It is never
    # sent through dictation cleanup, vocabulary substitution, or snippets.
    return groq.Outcome({"transcript": transcript.strip()}, cost)


def summarize(source, language, operation):
    system = (
        SUMMARY_INSTRUCTION
        + " Output language: "
        + (language if language != "auto" else "the source language")
        + "."
    )
    plan = groq.chat_plan(system, source, operation.reserved_cost)
    if plan is None:
        raise ledger.Rejected("allowance_exhausted")
    incoming_bound, outgoing_bound, ceiling = plan
    ledger.authorize(operation, ceiling)
    answer = groq.perform(
        "chat/completions",
        json={
            "model": MANAGED_NOTES_MODEL,
            "temperature": 0.1,
            "max_completion_tokens": outgoing_bound,
            "reasoning_effort": "low",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": source},
            ],
        },
    )
    incoming, outgoing = groq.token_usage(answer, incoming_bound, outgoing_bound)
    cost = money(incoming * groq.INPUT_RATE + outgoing * groq.OUTPUT_RATE, up=True)
    try:
        choice = answer["choices"][0]
        text = choice["message"]["content"]
        if (
            choice.get("finish_reason") != "stop"
            or not isinstance(text, str)
            or not text.strip()
            or len(text.encode()) > MAX_SOURCE_BYTES
        ):
            raise ValueError()
    except (KeyError, IndexError, TypeError, AttributeError, ValueError):
        raise groq.ProviderFailure(
            cost=cost, input_tokens=incoming, output_tokens=outgoing
        ) from None
    return groq.Outcome({"summary": text.strip()}, cost, incoming, outgoing)
