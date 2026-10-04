"""A static page for looking at a built DTB: navigation you can play, validation, lexicon."""
from __future__ import annotations

import html
import json
from pathlib import Path

E = html.escape


def page(out: Path, report: dict, validation: list[dict], intelligibility: dict | None = None) -> str:
    plan = json.loads((out / "plan.json").read_text())
    pars = {p["id"]: p for p in plan["pars"]}
    hdgs = f"dtb/{plan['pid']}hdgs.mp3"

    def nav_items(items: list[dict]) -> str:
        rows = []
        for n in items:
            p = pars[n["target"]]
            rows.append(
                f'<li><div class="row"><span class="cls">{E(n["cls"])}</span><span class="label">{E(n["label"])}</span>'
                f'<button data-src="{hdgs}" data-begin="{n["heading"][0]}" data-end="{n["heading"][1]}" title="Play the spoken label from the headings file">Label</button>'
                f'<button data-src="dtb/{E(p["audio"])}" data-begin="{p["clip"][0]}" title="Play the book from this point">Play from here</button>'
                f'<span class="where">{E(p["audio"])} · {p["clip"][0]:.3f}s</span></div>'
                + (f"<ul>{nav_items(n['children'])}</ul>" if n["children"] else "")
                + "</li>"
            )
        return "".join(rows)

    checks = "".join(f'<tr><td>{"✓" if c["ok"] else "✗"}</td><td>{E(c["check"])}</td><td class="detail">{E(c["detail"])}</td></tr>' for c in validation)
    passed = sum(c["ok"] for c in validation)
    hits: dict[str, str] = {}
    for h in report["lexicon_hits"]:
        hits.setdefault(h["text"], h["said"])
    lexicon = "".join(f"<tr><td>{E(k)}</td><td>{E(v)}</td></tr>" for k, v in hits.items())
    minutes = report["audio_seconds"] / 60
    asr_stat, asr_section = "", ""
    if intelligibility:
        asr_stat = f'<div class="stat"><b>{intelligibility["wer"] * 100:.1f}%</b><span>word error rate</span></div>'
        rows = "".join(f'<tr><td></td><td>{E(t["file"])}</td><td class="detail">{t["words"]} words, {t["wer"] * 100:.1f}% WER</td></tr>' for t in intelligibility["tracks"])
        asr_section = (
            "<h2>Intelligibility</h2><p class=\"lede\">Each track was transcribed with "
            f"{E(intelligibility['engine'])} and compared with the text the voice was given. Lower is clearer; "
            "most remaining differences are numbers written as digits, words that sound alike (marque, mark), 1787 spellings and signers' names.</p>"
            f"<table><tbody>{rows}</tbody></table>"
        )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(report['title'])} · sample talking book</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:wght@400;600;700&family=Young+Serif&display=swap">
<style>
:root{{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--line:rgba(11,11,11,.1);--accent:#1c5cab;--ok:#006300;--bad:#a12626}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--line:rgba(255,255,255,.1);--accent:#86b6ef;--ok:#0ca30c;--bad:#ff8a8a}}}}
:root[data-theme=dark]{{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--line:rgba(255,255,255,.1);--accent:#86b6ef;--ok:#0ca30c;--bad:#ff8a8a}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--page);color:var(--ink);font:400 16px/1.55 "Atkinson Hyperlegible Next",system-ui,sans-serif}}
main{{max-width:980px;margin:0 auto;padding:36px 16px 64px}}h1,h2{{font-family:"Young Serif",Georgia,serif;font-weight:400}}h1{{font-size:clamp(1.8rem,4vw,2.5rem);line-height:1.15;margin:6px 0 10px}}h2{{margin:36px 0 10px}}
.eyebrow{{font-size:.8rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--ink2)}}.lede{{max-width:66ch}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:10px;margin:18px 0}}.stat{{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 14px}}.stat b{{display:block;font-size:1.3rem}}.stat span{{color:var(--ink2);font-size:.85rem}}
.player{{position:sticky;top:0;z-index:2;background:var(--page);padding:10px 0;border-bottom:1px solid var(--line)}}audio{{width:100%}}
ul.tree,ul.tree ul{{list-style:none;margin:0;padding-left:18px}}ul.tree{{padding-left:0}}.row{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:6px 0;border-top:1px solid var(--line)}}
.cls{{font-size:.72rem;font-weight:700;color:var(--ink2);border:1px solid var(--line);border-radius:999px;padding:1px 8px}}.label{{font-weight:600}}.where{{color:var(--ink2);font-size:.82rem;margin-left:auto}}
button{{font:inherit;font-size:.82rem;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:8px;padding:3px 10px;cursor:pointer}}button:hover{{border-color:var(--accent)}}
table{{border-collapse:collapse;width:100%;background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:.92rem}}td,th{{text-align:left;padding:7px 12px;border-top:1px solid var(--line);vertical-align:top}}td:first-child{{width:28px;font-weight:700}}.detail{{color:var(--ink2)}}
.links{{font-weight:600}}.ok{{color:var(--ok)}}.bad{{color:var(--bad)}}footer{{margin-top:40px;color:var(--ink2);font-size:.88rem}}a{{color:var(--accent)}}
</style></head><body><main>
<p class="eyebrow">Sample digital talking book · ANSI/NISO Z39.86 · NLS Spec 1203</p>
<h1>{E(report['title'])}</h1>
<p class="lede">Built from an EPUB by a local pipeline: text parsed into navigable divisions, narrated with the {E(report['engine'])} voice <code>{E(report['voice'])}</code>, mastered to EBU R128 loudness, and packaged with OPF, NCX and SMIL files. Every clip time follows the Spec 1203 timing rule, and the checks below were run on the finished files.</p>
<p class="links"><a href="{E(plan['pid'])}-dtb.zip">Download the DTB (zip)</a> · <a href="https://github.com/howlshot/tts-talking-book">Source code</a></p>
<div class="stats">
<div class="stat"><b>{minutes:.0f} min</b><span>of narration</span></div>
<div class="stat"><b>{report['nav_points']}</b><span>navigation points</span></div>
<div class="stat"><b>{report['smil_pars']}</b><span>synchronized clips</span></div>
<div class="stat"><b>{report['realtime_factor']}×</b><span>faster than real time</span></div>
<div class="stat"><b class="{'ok' if passed == len(validation) else 'bad'}">{passed}/{len(validation)}</b><span>checks passed</span></div>
{asr_stat}
</div>
<div class="player"><audio id="player" controls preload="none"></audio></div>
<h2>Navigation</h2>
<ul class="tree">{nav_items(plan['nav'])}</ul>
<h2>Validation</h2>
<table><tbody>{checks}</tbody></table>
{asr_section}
<h2>Pronunciation lexicon</h2>
<p class="lede">Rules applied before synthesis, each logged for review. They fix the abbreviations in the signers' names.</p>
<table><thead><tr><th>Text</th><th>Spoken as</th></tr></thead><tbody>{lexicon}</tbody></table>
<footer>Text: the Constitution of the United States (1787), public domain. Narration: synthetic. Built by <a href="https://studiochingie.com/services">Studio Chingie LLC</a>. Audio is MP3 here; NLS delivery uses AMR-WB+ in 3GP.</footer>
</main>
<script>
const player = document.getElementById("player");
let stopAt = null;
player.addEventListener("timeupdate", () => {{ if (stopAt !== null && player.currentTime >= stopAt) {{ player.pause(); stopAt = null; }} }});
document.querySelectorAll("button[data-src]").forEach((b) => b.addEventListener("click", () => {{
  const begin = parseFloat(b.dataset.begin);
  stopAt = b.dataset.end ? parseFloat(b.dataset.end) : null;
  const start = () => {{ player.currentTime = begin; player.play(); }};
  if (!player.src.endsWith(b.dataset.src)) {{ player.src = b.dataset.src; player.addEventListener("loadedmetadata", start, {{ once: true }}); player.load(); }} else start();
}}));
</script></body></html>"""
