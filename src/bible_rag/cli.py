"""`bible-rag` command line. Agents call this through Bash; every command prints JSON.

    bible-rag serve                                  start the retrieval service (loads bge-m3)
    bible-rag health                                 is the service up?
    bible-rag search "q" ["variant" ...] [options]   hybrid search (needs the service)
    bible-rag search "q" --mode lexical              BM25 only, works without the service
    bible-rag verse JHN.3.16 [--source sblgnt,web]   exact lookup, works without the service
    bible-rag xref MRK.1.3 [--testament OT]          cross-references with relation class, no service
    bible-rag terms --corpus oshb_wlc חסד רחמים      how many verses contain each term, no service
    bible-rag draft translation ISA.7.14 --source oshb_wlc   skeleton with the original verbatim
    bible-rag validate runs/<id>/answer.json         anti-fabrication check, works without the service
    bible-rag check KIND FILE.json [--run ID]        check translation|terms|specialist|xrefs|analysis|answer
    bible-rag pack specialist|xrefs ...              assemble an agent result from the store, then check it
    bible-rag run new "question"                     create runs/<id>/ (prints the run_id)
    bible-rag run trace ID EVENT --agent A [--group G] [--detail ..] [--path ..] [--status ..]
    bible-rag run confidence ID                      evidence confidence from the specialist results
    bible-rag run answer ID                          synthesis.json -> answer.json + answer.md, validated
    bible-rag run show ID                            trace and files (demo mode)

Errors print {"error": ...} and exit non-zero: 1 for a bad request, 2 if the service is down.
`validate` exits 1 when the answer is invalid.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

from bible_rag.config import SERVICE_HOST, SERVICE_PORT

SERVICE_DOWN = (f"retrieval service is not running on {{url}}. Start it in a separate terminal "
                f"with: uv run bible-rag serve")


class ServiceDown(Exception):
    pass


def emit(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


def call(port, path, payload=None):
    url = f"http://{SERVICE_HOST}:{port}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = json.load(e).get("detail", str(e))
        emit({"error": detail}, 1)
    except (urllib.error.URLError, ConnectionError):
        raise ServiceDown(SERVICE_DOWN.format(url=f"http://{SERVICE_HOST}:{port}"))


def csv(value):
    return value.split(",") if value else None


def search(args):
    filters = {"language": csv(args.lang), "source": csv(args.source), "testament": csv(args.testament),
               "book_id": csv(args.book), "edition": csv(args.edition)}
    request = {"queries": args.queries, "lexical_queries": args.lexical or [], "filters": filters,
               "k": args.k, "candidates": args.candidates, "mode": args.mode, "context": args.context}
    if args.mode == "lexical":  # no embeddings needed, so don't require the service
        from bible_rag.retrieval import Retriever
        from bible_rag.store import VerseStore

        return Retriever(VerseStore()).search(**request)
    return call(args.port, "/search", request)


def verse(args):
    from bible_rag.store import VerseStore

    store = VerseStore()
    ref = args.ref.upper()
    rows = store.by_ref(ref, {"source": csv(args.source)})
    if not rows:
        emit({"error": f"no verse {ref}"}, 1)
    if args.context:
        for row in rows:
            row["context"] = store.context(row["verse_uid"], args.context, args.context)
    return {"canon_ref": ref, "verses": rows}


def xref(args):
    from bible_rag.crossrefs import ALLUSION_MIN_VOTES, VERIFIED_MIN_VOTES
    from bible_rag.store import VerseStore

    ref = args.ref.upper()
    links = VerseStore().cross_refs(ref, args.min_votes, args.testament, args.limit)
    return {"from": ref, "dataset": "openbible",
            "thresholds": {"verified": VERIFIED_MIN_VOTES, "possible_allusion": ALLUSION_MIN_VOTES},
            "links": links}


def draft(args):
    """Translation skeletons with the original copied verbatim, for a skill to fill in."""
    from bible_rag.store import VerseStore
    from bible_rag.validator import CORPUS_LABELS

    store, items = VerseStore(), []
    for ref in args.refs:
        rows = (list(store.get([ref]).values()) if ":" in ref
                else store.by_ref(ref.upper(), {"source": args.source}))
        rows = [r for r in rows if r["source"] == args.source and (not args.edition or r["edition"] == args.edition)]
        if not rows:
            items.append({"error": "unknown_reference", "input": ref,
                          "message": f"{ref} is not in {args.source}"})
            continue
        for row in rows:
            web = store.by_ref(row["canon_ref"], {"source": "web"})
            items.append({
                "canon_ref": row["canon_ref"], "verse_uid": row["verse_uid"], "source": row["source"],
                "corpus_label": CORPUS_LABELS[row["source"]], "original": row["text_display"],
                "translation": "", "method": "machine", "translator": "claude:",
                "literal_notes": [], "uncertainties": [] if row["alignment"] == "mapped" else
                [f"verse numbering alignment is {row['alignment']}"],
                "web_reference": web[0]["verse_uid"] if web else None, "differences_from_web": [],
                "_web_text": web[0]["text_display"] if web else None,  # remove before checking
                "_edition": row["edition"] or None,
            })
    return items if len(items) != 1 else items[0]


def terms(args):
    from bible_rag.store import VerseStore
    from bible_rag.validator import CORPUS_SOURCES

    counts = VerseStore().term_counts(args.terms, CORPUS_SOURCES[args.corpus])
    return {"corpus": args.corpus, "counts": counts,
            "missing": [t for t, n in counts.items() if n == 0]}


def validate(args, kind="answer"):
    from bible_rag import validator
    from bible_rag.store import VerseStore

    check = {"answer": validator.validate, "translation": validator.validate_translation,
             "terms": validator.validate_query_terms, "specialist": validator.validate_specialist,
             "xrefs": validator.validate_xrefs, "analysis": validator.validate_analysis}[kind]
    with open(args.path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            emit({"valid": False, "errors": [{"path": "$", "code": "json", "message": str(e)}],
                  "warnings": []}, 1)
    if kind == "answer":
        result = check(data, VerseStore(), getattr(args, "run", None))
    else:
        result = check(data, VerseStore())
    emit(result, 0 if result["valid"] else 1)


def pack(args):
    """Build the agent result, write it, then check it (exit 1 if the check fails)."""
    from bible_rag import results, validator
    from bible_rag.schemas import SPECIALIST_CORPUS
    from bible_rag.store import VerseStore

    store = VerseStore()
    if args.pack_kind == "specialist":
        obj = results.pack_specialist(
            args.agent, args.run, SPECIALIST_CORPUS[args.agent], args.search,
            results.load_json(args.selection), store, args.translations, args.context)
        check = validator.validate_specialist(obj, store)
    else:
        adjust = results.load_json(args.adjust) if args.adjust else None
        obj = results.pack_xrefs(args.run, args.refs, store, args.testament, args.min_votes,
                                 args.limit, adjust)
        check = validator.validate_xrefs(obj, store)
    results.write(obj, args.out)
    emit({"out": args.out, **check, "passages" if args.pack_kind == "specialist" else "entries":
          len(obj.get("passages", obj.get("entries", [])))}, 0 if check["valid"] else 1)


def run(args):
    from bible_rag import runs

    if args.run_cmd == "new":
        emit(runs.new_run(args.question, args.id))
    if not (runs.run_dir(args.id) / "trace.json").exists():
        emit({"error": f"no run {args.id}; create it with `bible-rag run new`"}, 1)
    if args.run_cmd == "trace":
        emit(runs.trace(args.id, args.event, args.agent, args.group, args.detail, args.path, args.status))
    if args.run_cmd == "confidence":
        c = runs.confidence(args.id)
        runs.save(c, runs.run_dir(args.id) / "confidence.json")
        emit(c)
    if args.run_cmd == "show":
        print(runs.show(args.id))
        sys.exit(0)
    if args.run_cmd == "answer":
        from pydantic import ValidationError

        from bible_rag import validator
        from bible_rag.schemas import SynthesisDraft
        from bible_rag.store import VerseStore

        d = runs.run_dir(args.id)
        draft = runs.load(d / "synthesis.json")
        try:
            SynthesisDraft.model_validate(draft)
        except ValidationError as e:
            emit({"valid": False, "errors": validator._schema_errors(e), "warnings": []}, 1)
        store = VerseStore()
        answer = runs.pack_answer(args.id, draft, store)
        result = validator.validate(answer, store, args.id)
        runs.save(answer, d / "answer.json")
        if result["valid"]:
            (d / "answer.md").write_text(runs.render(answer), encoding="utf-8")
        emit({"answer": str(d / "answer.json"), "markdown": str(d / "answer.md") if result["valid"] else None,
              **result}, 0 if result["valid"] else 1)


def serve(args):
    import uvicorn

    from bible_rag.server import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port)


def parser():
    p = argparse.ArgumentParser(prog="bible-rag", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="start the retrieval service")
    s.add_argument("--host", default=SERVICE_HOST)
    s.add_argument("--port", type=int, default=SERVICE_PORT)

    h = sub.add_parser("health", help="check the retrieval service")
    h.add_argument("--port", type=int, default=SERVICE_PORT)

    q = sub.add_parser("search", help="hybrid search")
    q.add_argument("queries", nargs="*", help="natural-language query and its variants")
    q.add_argument("--lexical", action="append", metavar="TERMS",
                   help="lexical-only query, e.g. Hebrew/Greek terms (repeatable)")
    q.add_argument("--lang", help="he, grc, en (comma-separated)")
    q.add_argument("--source", help="oshb_wlc, lxx_swete, sblgnt, web (comma-separated)")
    q.add_argument("--testament", help="OT, NT, DC")
    q.add_argument("--book", help="USFM book code(s), e.g. GEN,PSA")
    q.add_argument("--edition", help="og or th (LXX Daniel, Susanna, Bel)")
    q.add_argument("--k", type=int, default=10)
    q.add_argument("--candidates", type=int, default=30, help="hits per list before fusion")
    q.add_argument("--mode", choices=["hybrid", "vector", "lexical"], default="hybrid")
    q.add_argument("--context", type=int, default=0, help="neighbouring verses on each side")
    q.add_argument("--port", type=int, default=SERVICE_PORT)

    v = sub.add_parser("verse", help="exact lookup by canonical reference")
    v.add_argument("ref", help="e.g. JHN.3.16")
    v.add_argument("--source", help="comma-separated sources")
    v.add_argument("--context", type=int, default=0)

    x = sub.add_parser("xref", help="cross-references from a verse (OpenBible.info)")
    x.add_argument("ref", help="e.g. MRK.1.3")
    x.add_argument("--testament", choices=["OT", "NT", "DC"], help="only links into this testament")
    x.add_argument("--min-votes", type=int, help="default: the possible-allusion threshold")
    x.add_argument("--limit", type=int, default=20)

    d = sub.add_parser("draft", help="translation skeleton with the original copied verbatim")
    d.add_argument("kind", choices=["translation"])
    d.add_argument("refs", nargs="+", help="canon_refs (PSA.23.1) or verse_uids")
    d.add_argument("--source", required=True, choices=["oshb_wlc", "lxx_swete", "sblgnt"])
    d.add_argument("--edition", choices=["og", "th"], help="LXX Daniel/Susanna/Bel edition")

    t = sub.add_parser("terms", help="verse counts for search terms in a corpus")
    t.add_argument("terms", nargs="+")
    t.add_argument("--corpus", required=True,
                   choices=["oshb_wlc", "lxx_swete", "sblgnt", "lxx_swete+sblgnt"])

    c = sub.add_parser("validate", help="check an answer.json against the verse store")
    c.add_argument("path")

    k = sub.add_parser("check", help="check a skill's or agent's JSON output")
    k.add_argument("kind", choices=["translation", "terms", "specialist", "xrefs", "analysis", "answer"])
    k.add_argument("path")
    k.add_argument("--run", help="answer only: also check the confidence level against this run")

    r = sub.add_parser("run", help="run folders, trace, confidence and the final answer")
    r_sub = r.add_subparsers(dest="run_cmd", required=True)
    rn = r_sub.add_parser("new")
    rn.add_argument("question")
    rn.add_argument("--id", help="run id (default: timestamp + slug)")
    rt = r_sub.add_parser("trace")
    rt.add_argument("id")
    rt.add_argument("event", choices=["analysis", "delegate", "result", "skill", "check", "retry",
                                      "synthesis", "answer", "note"])
    rt.add_argument("--agent", required=True)
    rt.add_argument("--group", help="same value for delegations sent in parallel")
    rt.add_argument("--detail")
    rt.add_argument("--path")
    rt.add_argument("--status", choices=["ok", "failed", "empty"])
    for name in ("confidence", "show", "answer"):
        r_sub.add_parser(name).add_argument("id")

    pk = sub.add_parser("pack", help="assemble an agent result from the verse store, then check it")
    pk_sub = pk.add_subparsers(dest="pack_kind", required=True)
    ps = pk_sub.add_parser("specialist")
    ps.add_argument("--agent", required=True, choices=["english-retrieval-agent", "hebrew-specialist-agent",
                                                       "septuagint-specialist-agent", "greek-new-testament-agent"])
    ps.add_argument("--run", required=True, help="run id (folder under runs/)")
    ps.add_argument("--search", action="append", default=[], help="saved `bible-rag search` output (repeatable)")
    ps.add_argument("--selection", required=True, help="keep/discard JSON written by the agent")
    ps.add_argument("--translations", help="translation skill output for the kept verses")
    ps.add_argument("--context", type=int, default=0)
    ps.add_argument("--out", required=True)
    px = pk_sub.add_parser("xrefs")
    px.add_argument("refs", nargs="+", help="NT canon_refs to look up")
    px.add_argument("--run", required=True)
    px.add_argument("--testament", default="OT", choices=["OT", "NT", "DC"])
    px.add_argument("--min-votes", type=int)
    px.add_argument("--limit", type=int, default=20)
    px.add_argument("--adjust", help="JSON with downgrades and notes written by the agent")
    px.add_argument("--out", required=True)
    return p


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")  # Hebrew/Greek on a Windows console
    args = parser().parse_args(argv)
    try:
        if args.command == "serve":
            return serve(args)
        if args.command == "health":
            emit(call(args.port, "/health"))
        if args.command in ("validate", "check"):
            return validate(args, getattr(args, "kind", "answer"))
        if args.command == "pack":
            return pack(args)
        if args.command == "run":
            return run(args)
        emit({"search": search, "verse": verse, "xref": xref, "terms": terms,
              "draft": draft}[args.command](args))
    except ServiceDown as e:
        emit({"error": str(e)}, 2)
    except (ValueError, FileNotFoundError) as e:
        emit({"error": str(e)}, 1)
