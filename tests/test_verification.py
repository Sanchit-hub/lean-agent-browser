"""False-verified regression suite (release-blocking): pages where the action is sent but the outcome does
or doesn't happen (evals/bench/verification.py). On both engines:
- outcome did not happen -> the status must never be `verified`,
- outcome happened       -> the status must be `verified` (an honest miss here is a regression too).
scripts/verification_matrix.py runs the same cases N times and prints the confusion matrix."""
import pytest

from evals.bench.verification import CASES, classify, run_case
from tests.test_reliability import ENGINES, _session, base  # noqa: F401  (fixture)


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
async def test_verification_honesty(base, engine, case):  # noqa: F811
    bm, sess = await _session(base, engine)
    try:
        status, out = await run_case(sess, base, case)
    finally:
        await bm.close()
    cls = classify(case[5], status)
    assert cls != "FALSE_VERIFIED", f"{case[0]} ({case[6]}) on {engine}: claimed verified\n{out}"
    if case[5]:
        assert cls == "true_verified", f"{case[0]} ({case[6]}) on {engine}: outcome happened but status {status}\n{out}"


from evals.bench.verification import CASES_EXPECT, run_expect_case  # noqa: E402


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("case", CASES_EXPECT, ids=[c[0] for c in CASES_EXPECT])
async def test_expect_needs_fresh_unnegated_evidence(base, engine, case):  # noqa: F811
    bm, sess = await _session(base, engine)
    try:
        status, out = await run_expect_case(sess, base, case)
    finally:
        await bm.close()
    cls = classify(case[6], status)
    assert cls != "FALSE_VERIFIED", f"{case[0]} ({case[7]}) on {engine}: claimed verified\n{out}"
    if case[6]:
        assert cls == "true_verified", f"{case[0]} ({case[7]}) on {engine}: status {status}\n{out}"
