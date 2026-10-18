#!/usr/bin/env python
r"""Integration test notebook Kaggle (llama.cpp/GGUF): exec DUNG code cell voi tang HTTP GIA.

Khong can GPU, khong can model, khong can llama-server: thay gen_many bang ham gia tra ve
JSON nhu model that (mo phong tang HTTP toi llama-server).
Kiem tra: QA 5 lop, restore sentinel, fix_sentinels, renumber_sentinels, resume, MODE=failed.
"""
import json, os, re, sys, tempfile, threading, time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from games import load_profile, game_arg  # noqa: E402
from paths import notebook_path          # noqa: E402

NB = notebook_path(load_profile(game_arg()))
nb = json.load(open(NB, encoding="utf-8"))
codes = [c for c in nb["cells"] if c["cell_type"] == "code"]
S = lambda mark: next("".join(c["source"]) for c in codes if mark in "".join(c["source"]))
src_qa = S("def qa_check")
src_main = S("def worker_run(w, my_batches)")
print(f"da lay cell QA ({len(src_qa)} byte) + cell chinh ({len(src_main)} byte)")

g = dict(re=re, Counter=Counter, json=json, os=os, time=time, threading=threading,
         BATCH=2, MAX_BATCH_CHARS=2000, MAX_NEW_TOKENS=2048, MAX_PROMPT_TOKENS=6144,
         N_WORKERS=2, BATCH_PER_WORKER=2, USE_SCHEMA=True, PORTS=[8080, 8081],
         PIPELINE=True)
exec(compile(src_qa, "qa", "exec"), g)

CALLS = []


def _json_for(prompts, broken_single=None):
    out = []
    for p in prompts:
        m = re.search(r"### Source Data\n(\[.*\])\n\n### Output", p, re.S)
        assert m, "prompt thieu Source Data"
        arr = json.loads(m.group(1))
        if broken_single is not None and arr == broken_single:
            out.append(json.dumps(["{0>N\u0103ng l\u01b0\u1ee3ng{1> -{0}"], ensure_ascii=False))
        elif len(arr) > 1:
            out.append("Xin chao, day khong phai JSON")          # co tinh lam hong JSON
        else:
            out.append(json.dumps([f"VI {x}" for x in arr], ensure_ascii=False))
    return out


def fake_gen(worker, prompts, max_new_tokens=2048):
    CALLS.append((worker, len(prompts)))
    return _json_for(prompts, broken_single=["{0}Energy{1} -{2}"])


g["gen_many"] = fake_gen

units = [
    dict(uid=0, kind="ui", en="[{0}] {1}", masked="[{0}] {1}",
         maps=[["{0}", "{0}"], ["{1}", "{1}"]], skip=True, prefix=""),
    dict(uid=1, kind="ui", en="Open Bag", masked="Open Bag", maps=[], skip=False, prefix=""),
    dict(uid=2, kind="ui", en="narrator:Exactly right.", masked="Exactly right.",
         maps=[], skip=False, prefix="narrator:"),
    dict(uid=3, kind="ui", en="<color=#6F6F6F>Status: </color>Free",
         maps=[["{0}", "<color=#6F6F6F>"], ["{1}", "</color>"]],
         masked="{0}Status: {1}Free", skip=False, prefix=""),
    dict(uid=4, kind="ui", en="<color=#00FFA5>Energy</color> -{0}",
         maps=[["{0}", "<color=#00FFA5>"], ["{1}", "</color>"], ["{2}", "{0}"]],
         masked="{0}Energy{1} -{2}", skip=False, prefix=""),
]
tmp = tempfile.mkdtemp()
up = os.path.join(tmp, "units.jsonl")
with open(up, "w", encoding="utf-8") as f:
    for u in units:
        f.write(json.dumps(u, ensure_ascii=False) + "\n")

g.update(UNITS_PATH=up, MODE="all", OUT_PATH=os.path.join(tmp, "out.jsonl"),
         REVIEW_PATH=os.path.join(tmp, "rev.jsonl"))

print("--- chay cell chinh (MODE=all, JSON hong -> lui ve tung don vi) ---")
exec(compile(src_main, "main", "exec"), g)

recs = [json.loads(l) for l in open(g["OUT_PATH"], encoding="utf-8")]
by = {r["uid"]: r for r in recs}
assert set(by) == {0, 1, 2, 3, 4}, f"thieu uid: {sorted(by)}"
assert by[0]["note"] == "skipped", by[0]
assert by[2]["vi"] == "narrator:VI Exactly right.", f"tien to: {by[2]['vi']!r}"
assert "<color=#6F6F6F>Status: </color>Free" in by[3]["vi"], f"sentinel: {by[3]['vi']!r}"
want4 = "<color=#00FFA5>N\u0103ng l\u01b0\u1ee3ng</color> -{0}"
assert by[4]["vi"] == want4, f"uid4: {by[4]['vi']!r}"
assert all(r["qa_ok"] for r in recs), \
    f"con loi: {[(r['uid'], r.get('problems')) for r in recs if not r['qa_ok']]}"
print("  uid 2:", repr(by[2]["vi"]))
print("  uid 3:", repr(by[3]["vi"]))
print("  uid 4:", repr(by[4]["vi"]), "<- fix_sentinels + renumber_sentinels")
print(f"  so lan goi model: {len(CALLS)} {CALLS}")

n0 = len(CALLS)
exec(compile(src_main, "main2", "exec"), {**g})
assert len(CALLS) == n0, f"resume van goi model: {len(CALLS)-n0} lan"
print("  resume: khong goi lai (OK)")


# Hai nhanh trong worker_run deu phai chay: cua so truot (PIPELINE) va chia lo (duong cu).
# N_WORKERS=1 de nhieu luong cua so truot chay TRONG CUNG mot worker_run.
def _rerun(tag, **kw):
    gg = dict(g, OUT_PATH=os.path.join(tmp, f"out_{tag}.jsonl"), MODE="all")
    gg.update(kw)
    gg["gen_many"] = fake_gen
    CALLS.clear()
    exec(compile(src_main, f"main_{tag}", "exec"), gg)
    rr = {json.loads(l)["uid"]: json.loads(l) for l in open(gg["OUT_PATH"], encoding="utf-8")}
    assert rr[2]["vi"] == "narrator:VI Exactly right.", f"{tag} uid2: {rr[2]['vi']!r}"
    assert rr[3]["vi"] == by[3]["vi"], f"{tag} uid3: {rr[3]['vi']!r}"
    assert rr[4]["vi"] == want4, f"{tag} uid4: {rr[4]['vi']!r}"
    assert all(r["qa_ok"] for r in rr.values()), f"{tag}: con loi QA"
    print(f"  {tag}: {len(CALLS)} lan goi model, ket qua y het -> OK")


_rerun("cua_so_truot", PIPELINE=True, N_WORKERS=1)
_rerun("chia_lo", PIPELINE=False, N_WORKERS=1)

g2 = dict(g, MODE="failed", OUT_PATH=os.path.join(tmp, "out2.jsonl"))
with open(g2["OUT_PATH"], "w", encoding="utf-8") as f:
    f.write(json.dumps(dict(uid=1, vi="Tui da mo", qa_ok=True, note="x"), ensure_ascii=False) + "\n")
    f.write(json.dumps(dict(uid=2, vi="sai", qa_ok=False, note="x"), ensure_ascii=False) + "\n")
    # Dong hong khi goi server: vi = ban goc EN. Don vi nhu vay LUON lot qua qa_check
    # (token giong giong nhau) — duy cot "error" de MODE=failed phai dich lai.
    f.write(json.dumps(dict(uid=3, vi=units[3]["en"], qa_ok=False, note="error",
                            error="URLError: [Errno 111] Connection refused"),
             ensure_ascii=False) + "\n")
g2["gen_many"] = fake_gen
CALLS.clear()
exec(compile(src_main, "main3", "exec"), g2)
r2 = {json.loads(l)["uid"]: json.loads(l) for l in open(g2["OUT_PATH"], encoding="utf-8")}
# uid 1 da co trong file output va ban dich CU dat QA -> phai giu nguyen, khong goi model.
# uid 2 (tien to "narrator:" bi mat) -> phai dich lai.
# uid 3 co cot "error" (vi = EN goc) -> phai dich lai chu khong duoc cong la dich duoc ROI.
assert r2[1]["vi"] == "Tui da mo", f"uid 1 bi dich lai ngoai y muon: {r2[1]['vi']!r}"
assert r2[2]["vi"] == "narrator:VI Exactly right.", f"uid 2 khong duoc dich lai: {r2[2]['vi']!r}"
assert r2[3].get("error") is None and r2[3].get("qa_ok"), f"uid 3 chua duoc dich lai: {r2[3]!r}"
assert len(CALLS) >= 1, "uid 2/3 phai duoc goi model"
print(f"  MODE=failed: giu uid 1, dich lai uid 2 + uid 3 (error) ({len(CALLS)} lan goi model) OK")

print("\nTAT CA TEST PASS")
