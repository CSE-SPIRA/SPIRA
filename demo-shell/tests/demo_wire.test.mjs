import assert from "node:assert/strict";
import test from "node:test";
import { lineReaction, reactionConfirmed, readProblem, rehearsalControls, shareControls, stageNotice, startedLines } from "../ui/wire.js";
import { replayFrames } from "../ui/run.js";

test("a real run renders only screenshot upload and never generates the sample order", () => {
  const markup = shareControls(false, () => assert.fail("sample generated"), "", "");
  assert.match(markup, /id="files"/);
  assert.doesNotMatch(markup, /id="sample"|scan-picture/);
  assert.match(shareControls(true, () => "fixture.png", "", ""), /fixture\.png/);
});

test("missing rationale has its own state for context, intent, and tasks", () => {
  const problems = { rationale: readProblem(404) };
  for (const stage of ["context", "intent", "tasks", "record"]) {
    assert.equal(stageNotice(stage, problems), "서버가 아직 이 단계를 내보내지 않아요");
  }
  for (const stage of ["extract", "plan", "hub"]) assert.equal(stageNotice(stage, problems), undefined);
  assert.equal(readProblem(405), "missing");
  assert.equal(readProblem(401), "failed");
  assert.equal(readProblem(200), null);
  assert.equal(readProblem(503), null);
  const entries = [
    { kind: "read_problem", data: { source: "rationale", problem: "missing" }, read: 2 },
    { kind: "rationale", data: {}, read: 1 },
  ];
  assert.equal(replayFrames(entries).judgment.readProblems.rationale, "missing");
  entries.push({ kind: "rationale", data: {}, read: 3 });
  assert.equal(replayFrames(entries).judgment.readProblems.rationale, null);
});

test("the advance control needs both clock and moments and stays hidden on replay", () => {
  assert.deepEqual(rehearsalControls(null, false, true, false), { advance: false, unavailable: true });
  assert.equal(rehearsalControls({}, false, false, false).advance, false);
  assert.equal(rehearsalControls({}, true, false, false).advance, true);
  assert.equal(rehearsalControls({}, true, false, true).advance, false);
});

test("a pending line-on is confirmed only by the Server's replacement task", () => {
  const old = { task_id: "t_clean#1", checked: false, state: "off" };
  const active = { task_id: "t_clean#7", checked: true, state: "scheduled" };
  const other = { task_id: "t_mood#3", checked: true, state: "scheduled" };
  const pending = { reaction: "line_on", taskId: old.task_id, before: [old, other], ack: { lines: [active, other] } };
  assert.equal(reactionConfirmed({ lines: [old, other] }, pending), false);
  assert.equal(reactionConfirmed({ lines: [other] }, pending), false);
  assert.equal(reactionConfirmed({ lines: [active, other] }, pending), true);
});

test("card switches follow the App's started, ended and stopped rules", () => {
  const a = { task_id: "t_a#1", state: "scheduled", end_state: null };
  const b = { task_id: "t_b#2", state: "off", end_state: null };
  const c = { task_id: "t_c#3", state: "running", end_state: null };
  const d = { task_id: "t_d#4", state: "off", end_state: "restored" };
  const card = { stopped: false, lines: [a, b, c, d] };
  const started = startedLines(new Set(), [card], [{ task_id: a.task_id, status: "blocked" }]);
  assert.deepEqual([...started], [c.task_id, d.task_id]);
  assert.deepEqual(card.lines.map((line) => lineReaction(card, line, started)), ["line_off", "line_on", "line_off", null]);
  assert.equal(lineReaction(card, { ...c, state: "off" }, started), null);
  assert.equal(lineReaction(card, { ...c, state: "failed" }, started), "line_off");
  assert.equal(lineReaction(card, a, started, "closed"), null);
  assert.equal(lineReaction({ ...card, stopped: true }, a, started), null);
});
