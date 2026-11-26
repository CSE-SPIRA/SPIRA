"""server/scripts/dry_run.py on two fake screenshots with canned LLM answers (no keys, no model download).

The real run (handoff §6 step 5/6) uses real photos, a real LLM and BGE-M3; this only proves the tool works end to end:
home seeding, upload, S1..S5, the nine output files and checks.txt.
"""

import importlib.util
import json
import sys

from spira_server.config import load_yaml
from spira_server.llm import client as llm_client
from spira_server.llm.client import RawReply
from spira_server.paths import SERVER_DIR

from . import kb_seed
from .factories import data, png

spec = importlib.util.spec_from_file_location("dry_run", SERVER_DIR / "scripts" / "dry_run.py")
dry_run = importlib.util.module_from_spec(spec)
sys.modules["dry_run"] = dry_run
spec.loader.exec_module(dry_run)

OUTPUT_FILES = ["s1_items.json", "s2_context.json", "s3_message.txt", "s3_intent.json", "s4_tasks.json",
                "plan.json", "card.json", "llm_calls.jsonl", "llm_io.jsonl", "checks.txt"]
TAGS = {"c1": ["생일"], "c2": ["가족 모임"], "c3": ["회의"], "c4": [], "c5": ["운동"]}


class StageProvider:
    """Answers by stage, whatever the message (the real message is checked in the S1-S5 tests)."""
    name, model = "mock", "canned"

    def __init__(self, outputs):
        self.outputs = outputs

    def complete(self, *, stage, **_):
        return RawReply(data=self.outputs[stage], input_tokens=100, output_tokens=10)


def _canned():
    s3 = data("s3_ep_9031.json")["decision"]
    return {"s1": data("s1_ep_9031.json")["output"],
            "cal": {"events": [{"id": k, "tags": v} for k, v in TAGS.items()]},
            "s3": s3, "s4": data("s4_ep_9031.json")["output"]}


def _folder(tmp_path, answer: str | None):
    folder = tmp_path / "01_birthday"
    folder.mkdir()
    (folder / "a.png").write_bytes(png(1))
    (folder / "b.png").write_bytes(png(2))
    if answer is not None:
        (folder / "answer.txt").write_text(answer, encoding="utf-8")
    return folder


ANSWER = """딸기 · 2
컵케이크 믹스 · ?
휘핑크림 · 1
세탁 세제 · 1
로션 · 1
풍선 · 1
케이크 토퍼 · 1
고깔모자 · 6
아이싱 펜 · 1
제외: 위쪽 배송지 영역은 가림
"""


def test_dry_run_end_to_end(tmp_path, monkeypatch, env):
    env(KB_MODE="off")
    llm_client.set_llm(llm_client.LLM(StageProvider(_canned())))
    out = tmp_path / "out"
    code = dry_run.main(["--images", str(_folder(tmp_path, ANSWER)), "--home",
                         str(SERVER_DIR / "dev" / "home.example.yaml"), "--kb", "off",
                         "--now", "2026-10-15T21:00:08+09:00", "--out", str(out), "--resend"])
    checks = (out / "checks.txt").read_text(encoding="utf-8")
    assert code == 0, checks
    assert checks.startswith("PASS ")
    for name in OUTPUT_FILES:
        assert (out / name).exists(), name
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    assert [t["task_id"] for t in plan["tasks"]] == [
        "t_clean#1", "t_safe#2", "t_mood#3", "t_oven#4", "t_fridge#5", "t_fridge#6"]
    [card] = json.loads((out / "card.json").read_text(encoding="utf-8"))
    assert card["text"] == "토요일 생일(디즈니 공주 테마)에 맞춰 집을 준비해 둘게요"
    assert "[캘린더 일정]\n" in (out / "s3_message.txt").read_text(encoding="utf-8")
    io = [json.loads(x) for x in (out / "llm_io.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["stage"] for x in io] == ["cal", "s1", "s3", "s4"]
    assert "[ok] resend: same episode, 200" in checks
    from spira_server.db.engine import session_scope
    from spira_server.db.models import Episode
    with session_scope() as s:
        ep = s.query(Episode).filter(Episode.household_id == "h_dry").order_by(Episode.created_at.desc()).first()
        keys = ["received", "s1_start", "s1", "s2", "s3", "s4", "s5"]
        assert list(ep.stage_times) == keys or sorted(ep.stage_times) == sorted(keys)
        times = [ep.stage_times[k] for k in keys]
        assert times == sorted(times)                        # wall times, in stage order
        assert [d["task_id"] for d in ep.s4["drafts"]] == [t["task_id"] for t in plan["tasks"]]
        assert ep.s4["llm_called"] is True and "0" in ep.s4["whens"]


def test_answer_mismatch_fails(tmp_path, env):
    env(KB_MODE="off")
    llm_client.set_llm(llm_client.LLM(StageProvider(_canned())))
    out = tmp_path / "out"
    code = dry_run.main(["--images", str(_folder(tmp_path, "딸기 · 3\n감기약 · 1 · 가림\n")),
                         "--home", str(SERVER_DIR / "dev" / "home.example.yaml"),
                         "--now", "2026-10-15T21:00:08+09:00", "--out", str(out)])
    checks = (out / "checks.txt").read_text(encoding="utf-8")
    assert code == 1 and checks.startswith("FAIL ")
    assert "[FAIL] answer: 딸기 — read as 딸기 × 2" in checks
    assert "[FAIL] answer: masked items — 0 masked, 1 expected" in checks
    assert "[FAIL] answer: no extra items" in checks


def test_llm_failures_are_reported(tmp_path, env):
    env(KB_MODE="off")
    canned = _canned()
    canned["cal"] = {"events": [{"id": "c1", "tags": ["병원"]}]}          # not a calendar tag: tagging fails
    llm_client.set_llm(llm_client.LLM(StageProvider(canned)))
    out = tmp_path / "out"
    code = dry_run.main(["--images", str(_folder(tmp_path, None)), "--home",
                         str(SERVER_DIR / "dev" / "home.example.yaml"), "--now", "2026-10-15T21:00:08+09:00",
                         "--out", str(out)])
    checks = (out / "checks.txt").read_text(encoding="utf-8")
    assert code == 1
    assert "[FAIL] every LLM call answered in format — cal: format_fail" in checks
    assert "[FAIL] S3 judged without a format failure" in checks


def test_blocked_home_stops(tmp_path, env):
    env(KB_MODE="off")
    home = load_yaml((SERVER_DIR / "dev" / "home.example.yaml").read_text(encoding="utf-8"))
    home["household_types"] = ["3~4인", "영유아 자녀", "맞벌이"]
    path = tmp_path / "home.yaml"
    path.write_text(json.dumps(home, ensure_ascii=False), encoding="utf-8")
    llm_client.set_llm(llm_client.LLM(StageProvider(_canned())))
    code = dry_run.main(["--images", str(_folder(tmp_path, None)), "--home", str(path),
                         "--now", "2026-10-15T21:00:08+09:00", "--out", str(tmp_path / "out")])
    assert code == 2


def test_parse_answer():
    assert dry_run.parse_answer("딸기 · 2\n컵케이크 믹스 · ?\n감기약 · 1 · 가림\n제외: 메모\n\n") == [
        {"name": "딸기", "qty": 2, "masked": False}, {"name": "컵케이크 믹스", "qty": None, "masked": False},
        {"name": "감기약", "qty": 1, "masked": True}]


def test_earlier_runs_are_not_counted(tmp_path, env):
    """A failed run before must not fail the next run's LLM check (dry run A, 11-21: llm_calls of the last hour)."""
    env(KB_MODE="off")
    canned = _canned()
    canned["cal"] = {"events": [{"id": "c1", "tags": ["병원"]}]}
    llm_client.set_llm(llm_client.LLM(StageProvider(canned)))
    home = str(SERVER_DIR / "dev" / "home.example.yaml")
    first = tmp_path / "first"
    first.mkdir()
    dry_run.main(["--images", str(_folder(first, None)), "--home", home, "--now", "2026-10-15T21:00:08+09:00",
                  "--out", str(tmp_path / "out1")])
    llm_client.set_llm(llm_client.LLM(StageProvider(_canned())))
    second = tmp_path / "second"
    second.mkdir()
    out = tmp_path / "out2"
    code = dry_run.main(["--images", str(_folder(second, ANSWER)), "--home", home,
                         "--now", "2026-10-15T21:00:08+09:00", "--out", str(out)])
    checks = (out / "checks.txt").read_text(encoding="utf-8")
    assert code == 0, checks
    calls = [json.loads(x) for x in (out / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [c["stage"] for c in calls] == ["cal", "s1", "s3", "s4"]
    io = [json.loads(x) for x in (out / "llm_io.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {x["stage"]: x["enforce_schema"] for x in io} == {"cal": True, "s1": True, "s3": True, "s4": False}


def _kb_run(tmp_path, env, **extra_env):
    env(KB_MODE="on", KB_VERSION="kb-v1", **extra_env)
    kb_seed.clear()
    kb_seed.seed_birthday_neighbours()
    llm_client.set_llm(llm_client.LLM(StageProvider(_canned())))
    out = tmp_path / "out"
    code = dry_run.main(["--images", str(_folder(tmp_path, ANSWER)), "--home",
                         str(SERVER_DIR / "dev" / "home.example.yaml"), "--kb", "on",
                         "--now", "2026-10-15T21:00:08+09:00", "--out", str(out)])
    return code, out


def test_kb_on_writes_search_table_and_sweep(tmp_path, env):
    """dry run B (11-21): every searched case with sim, bonus and used rank; floors x caps and KB_SAMPLE sizes."""
    code, out = _kb_run(tmp_path, env)
    checks = (out / "checks.txt").read_text(encoding="utf-8")
    assert code == 0, checks
    assert "[ok] S2 KB searched — 15 cases, 12 above 0.7, used 12, top sim" in checks
    rows = [r.split("\t") for r in (out / "kb_search.tsv").read_text(encoding="utf-8").splitlines()]
    assert rows[0] == dry_run.TSV_COLUMNS and len(rows) == 16
    col = {name: k for k, name in enumerate(rows[0])}
    body = rows[1:]
    sims = [float(r[col["sim"]]) for r in body]
    assert sims == sorted(sims, reverse=True)
    assert sum(1 for r in body if r[col["used_rank"]]) == 12
    assert {r[col["case_id"]] for r in body if r[col["rep"]] == "y"} == {
        e["case_id"] for e in json.loads((out / "s2_context.json").read_text(encoding="utf-8"))
        ["for_intent"]["kb_neighbors"]["examples"]}
    assert all(r[col["cal_bonus"]] == "0.05" for r in body if r[col["calendar_tags"]] == "생일")   # c1 생일
    assert all(r[col["ox"]] == "" for r in body)
    sweep = (out / "kb_sweep.txt").read_text(encoding="utf-8")
    assert "floor 0.70 cap  50: above  12, used  12 | kid_birthday_party 9 · home_baking 2 · none 1 " \
           "| reps kid_birthday_party, home_baking  <- now" in sweep
    assert "floor 0.60 cap  20" in sweep and "floor 0.75 cap 200" in sweep
    assert "S3 counts (share here / share in the KB of 15): kid_birthday_party 9 (75% / 60%) · " \
           "home_baking 2 (17% / 13%) · none 1 (8% / 27%)" in sweep
    assert "sample 0.25:" in sweep and "sample 0.5 :" in sweep and "sample 1.0 :" in sweep


def test_kb_down_fails_the_kb_check(tmp_path, env):
    """A KB failure ends S2 as judged/done; without this check it looked like a correct 'no intent' (03_grocery)."""
    code, out = _kb_run(tmp_path, env, KB_DATABASE_URL="postgresql://spira:spira@localhost:1/nothing")
    checks = (out / "checks.txt").read_text(encoding="utf-8")
    assert code == 1
    assert "[FAIL] S2 KB searched — KB unavailable" in checks
    assert not (out / "kb_search.tsv").exists()


def test_used_band_counts_cases_lifted_by_the_bonus(env):
    from spira_server.config import Numbers, get_config
    from spira_server.kb.search import KbCase

    env(KB_MODE="off")
    n = Numbers({**get_config().numbers.as_dict(), "max_use": 2})
    case = lambda cid, sim, tags: KbCase(cid, ["딸기"], "kid_birthday_party", None, {},  # noqa: E731
                                          {"calendar_tags": tags}, {"types": []}, sim)
    cases = [case("a", 0.80, []), case("b", 0.79, []), case("c", 0.77, ["생일"])]
    band, moved, lifted = dry_run._used_band(cases, [{"tags": ["생일"]}], [], True, n)
    assert moved == 1 and [c.case_id for c in lifted] == ["c"]                 # 0.77 + 0.05 > 0.79
    assert band == "0.800 ~ 0.770 (band 0.030)"
