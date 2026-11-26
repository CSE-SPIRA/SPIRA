import assert from "node:assert/strict";
import test from "node:test";
import { readProblem, rehearsalControls, stageNotice } from "../ui/wire.js";
import { replayFrames } from "../ui/run.js";

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
