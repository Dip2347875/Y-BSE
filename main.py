"""python main.py --mode long|short [--now] [--dry-run] [--book "Title|Author"]"""
import argparse, json, shutil, traceback
import config, brain, book_finder, script_writer, voice, editor, thumbnail, seo, uploader


def log(*a):
    print(*a, flush=True)


def make_long_script(d):
    """Local-AI script from deep research; returns None when there is not enough material for a 1h45+ video."""
    try:
        import local_ai, analyst, sources
        local_ai.start_budget(config.AI_BUDGET_MIN)
        srcs = sources.gather(d, log)
        total = sum(s["words"] for s in srcs)
        log(f"[sources] {len(srcs)} sources, {total} words in total")
        if total < config.MIN_SOURCE_WORDS:
            log("[skip] not enough research material for this book")
            return None
        secs = analyst.write_long(d, srcs, log)
        if secs:
            return secs
        log("[ai] no script produced")
        return None
    except Exception:
        traceback.print_exc()
        log("[ai] local AI unavailable - using the simple template script instead")
        return script_writer.compose_long(d)


def make_short_script(d, idx):
    if idx < len(d["concepts"]):
        c = d["concepts"][idx]
        try:
            import analyst
            text = analyst.write_short(d, c["term"], c["text"])
            if text:
                return c["term"], text
        except Exception:
            traceback.print_exc()
            log("[ai] local AI unavailable for the Short - using the template")
    return script_writer.compose_short(d, idx)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["long", "short"], required=True)
    ap.add_argument("--now", action="store_true", help="publish immediately")
    ap.add_argument("--dry-run", action="store_true", help="make the video but do not upload")
    ap.add_argument("--book", help='"Title|Author" to force a specific book')
    a = ap.parse_args()
    cfg = config.LONG if a.mode == "long" else config.SHORT

    br = brain.Brain()
    chosen, tries = None, 0
    for book in book_finder.next_books(br, a.mode, a.book):
        tries += 1
        if tries > 12:
            break
        key = br.claim(book["title"], book.get("author", ""))
        br.save()
        log(f"=== {a.mode.upper()} :: {book['title']} - {book.get('author', '')}")
        try:
            wd = config.WORK / key
            wd.mkdir(parents=True, exist_ok=True)
            stored = br.books[key].get("ideas") or []
            if a.mode == "short" and stored:
                d = book_finder.research_light(book, wd)      # deep research already saved in the brain
                d["concepts"] = stored
            else:
                d = book_finder.research(book, wd)
            if a.mode == "long":
                sections, idea = make_long_script(d), None
                if not sections:
                    br.mark_skipped(key, "not enough material for a long video")
                    br.save()
                    continue
                br.set_ideas(key, d["concepts"]) if d["concepts"] else None
            else:
                r = make_short_script(d, br.short_count(key))
                if not r:
                    br.mark_skipped(key, "no short idea available")
                    br.save()
                    continue
                idea = r[0]
                sections = [dict(title=idea, text=r[1])]
                if not stored and d["concepts"]:
                    br.set_ideas(key, d["concepts"])
            br.set_concepts(key, [c["term"] for c in d["concepts"]])
            chosen = (key, d, sections, idea)
            break
        except Exception as e:
            traceback.print_exc()
            br.mark_failed(key, e)
            br.save()
    if not chosen:
        raise SystemExit("No suitable book found this run.")

    key, d, sections, idea = chosen
    try:
        wd = config.WORK / key
        scenes = script_writer.build_scenes(sections, d, a.mode, log)
        (wd / "scenes.json").write_text(json.dumps(scenes, indent=1, ensure_ascii=False))
        total = voice.synthesize(scenes, wd / "audio")
        log(f"[voice] narration length: {total / 60:.1f} min")
        out_video = config.OUT / f"{key}-{a.mode}.mp4"
        editor.render_video(scenes, d, wd / "render", out_video, cfg, log)

        chapters = seo.chapter_marks(scenes) if a.mode == "long" else None
        meta = seo.build(d, a.mode, chapters, idea)
        thumb = None
        if a.mode == "long":
            thumb = thumbnail.make_thumbnail(d["cover"], *meta["thumb"], d["author"], config.OUT / f"{key}-thumb.jpg")
        (config.OUT / f"{key}-{a.mode}-meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        log("[seo]", meta["title"])
        if a.dry_run:
            log("[dry-run] skipping upload")
            return

        pl_title = f"{meta['category']} \u2014 Book " + ("Summaries" if a.mode == "long" else "Shorts")
        pl_desc = f"Every {meta['category'].lower()} book, explained."
        vid = uploader.upload(out_video, meta, thumb, pl_title, pl_desc, br.data, a.mode, publish_now=a.now, log=log)
        if a.mode == "long":
            br.add_long(key, vid, meta["category"])
        else:
            br.add_short(key, idea, vid)
        br.save()
        shutil.rmtree(wd, ignore_errors=True)
        out_video.unlink(missing_ok=True)
    except Exception as e:
        traceback.print_exc()
        br.mark_failed(key, e)
        br.save()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
