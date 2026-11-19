"""Spec §6.2 call rule: two attempts, retry text lists only the errors, stage default, one llm_calls row."""

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from spira_server.db.models import LlmCall
from spira_server.llm.client import call_with_retry, get_llm, retry_text
from spira_server.llm.mock import MockMissing

SYSTEM = "시스템"
USER = "질문"
RETRY = "앞의 답에 형식 오류가 있다.\n{ERRORS}"


class Answer(BaseModel):
    n: int


def _rows(session):
    return session.execute(select(LlmCall)).scalars().all()


def _call(**kw):
    return call_with_retry(get_llm(), stage="s3", system=SYSTEM, user=USER, schema=Answer, retry_template=RETRY,
                           default="DEFAULT", episode_id="ep_1", **kw)


def _retry_user(errors):
    return USER + "\n\n" + retry_text(RETRY, errors)


def test_ok_first_time(mock_llm, session):
    mock_llm.record("s3", SYSTEM, USER, output={"n": 3}, usage={"input": 10, "output": 2})
    r = _call()
    assert (r.ok, r.value.n, r.attempts, r.outcome) == (True, 3, 1, "ok")
    [row] = _rows(session)
    assert (row.stage, row.attempts, row.outcome, row.input_tokens, row.episode_id) == ("s3", 1, "ok", 10, "ep_1")


def test_stage_check_retries_with_only_its_errors(mock_llm, session):
    mock_llm.record("s3", SYSTEM, USER, output={"n": -1})
    mock_llm.record("s3", SYSTEM, _retry_user(["n는 0 이상"]), output={"n": 1})
    r = _call(check=lambda a: ["n는 0 이상"] if a.n < 0 else [])
    assert (r.ok, r.value.n, r.attempts) == (True, 1, 2)
    assert _rows(session)[0].attempts == 2


def test_two_failures_give_default(mock_llm, session):
    mock_llm.record("s3", SYSTEM, USER, refusal=True)
    refusal = "답하지 않고 거절했다. 스키마에 맞는 JSON으로 답해야 한다."
    mock_llm.record("s3", SYSTEM, _retry_user([refusal]), text="잘 모르겠어요. 어떤 주문인가요?")
    r = _call()
    assert (r.ok, r.value, r.outcome) == (False, "DEFAULT", "format_fail")
    assert _rows(session)[0].outcome == "format_fail"


def test_timeout_twice(mock_llm, session):
    mock_llm.record("s3", SYSTEM, USER, timeout=True)
    r = _call()
    assert (r.value, r.outcome, r.attempts) == ("DEFAULT", "timeout", 2)
    assert mock_llm.calls("s3") == 2


def test_schema_failure_is_a_format_error(mock_llm):
    mock_llm.record("s3", SYSTEM, USER, output={"n": "many"})
    error = "n: Input should be a valid integer, unable to parse string as an integer"
    mock_llm.record("s3", SYSTEM, _retry_user([error]), output={"n": 2})
    assert _call().value.n == 2


def test_raw_mode_returns_dict(mock_llm):
    mock_llm.record("s3", SYSTEM, USER, output={"n": "not-validated"})
    assert _call(raw=True).value == {"n": "not-validated"}


def test_unrecorded_call_raises(mock_llm):
    with pytest.raises(MockMissing):
        _call()
