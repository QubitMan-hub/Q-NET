"""One QPV_BB84 round, step by step, using qpvsim.qpv.messages.

    python scripts/run_round.py
"""

import random

from qpvsim import timeunits as tu
from qpvsim.qpv.messages import (classical_verifier_message, prover_measure, prover_response,
                                 quantum_verifier_message, validate_response)


def run_round(qv_pos, cv_pos, claim, prover_pos, t_ref_fs, tolerance_fs, rng=random):
    # shared secrets of the verifiers
    x, shares = rng.randint(0, 1), [rng.randint(0, 1)]

    # 1. classical verifier -> prover
    cv = classical_verifier_message("CV", cv_pos, claim, shares[0], t_ref_fs)
    print(f"1. CV sends share={cv['share']} at {tu.fmt(cv['send_fs'])}")

    # 2. quantum verifier -> prover
    qv = quantum_verifier_message("QV", qv_pos, claim, x, shares, t_ref_fs)
    print(f"2. QV sends qubit {qv['qubit'].round(3)} at {tu.fmt(qv['send_fs'])}")

    # 3. prover measures
    answer = prover_measure(qv, [cv], rng=rng)
    print(f"3. prover measures in basis {shares[0]} -> {answer}")

    # 4. prover -> both verifiers
    replies = prover_response("P", prover_pos, answer, [qv, cv])
    for vid, r in replies.items():
        print(f"4. prover answer {r['value']} reaches {vid} at {tu.fmt(r['arrival_fs'])}")

    # 5. each verifier checks the answer; the position is verified only if all accept
    results = {"QV": validate_response(replies["QV"], qv_pos, claim, x, t_ref_fs, tolerance_fs),
               "CV": validate_response(replies["CV"], cv_pos, claim, x, t_ref_fs, tolerance_fs)}
    for vid, r in results.items():
        print(f"5. {vid}: correct={r['correct']} on_time={r['on_time']} deadline={tu.fmt(r['deadline_fs'])}")
    verified = all(r["accepted"] for r in results.values())
    print(f"   position {'VERIFIED' if verified else 'REJECTED'} (x={x})")
    return verified


if __name__ == "__main__":
    qv, cv, claim = [-3.0, 0.0], [3.0, 0.0], [0.0, 0.0]
    print("--- honest prover at the claim")
    run_round(qv, cv, claim, claim, tu.ns(20), tu.ns("0.5"))
    print("--- prover 1 m off the claim")
    run_round(qv, cv, claim, [-1.0, 0.0], tu.ns(20), tu.ns("0.5"))
