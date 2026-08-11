"""shots.json + assets/ から陣取り紅白戦PVを ffmpeg で合成するCLI。

使い方:
  python build/make_movie.py --preview   # 低解像度ドラフト。未投入クリップはプレースホルダーで代用
  python build/make_movie.py             # 本番書き出し。未投入クリップがあれば警告しつつプレースホルダーで代用

前提: promo/assets/clips/{id:02d}.<ext> にAI生成クリップ等を置く。
      promo/assets/bgm/ にBGM音源を1本置く。
      promo/assets/se/{id:02d}.<ext> で任意のカット単体SEを置くとそのカット開始位置にミックスされる。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parse_storyboard  # noqa: E402

BUILD_DIR = Path(__file__).resolve().parent
PROMO_DIR = BUILD_DIR.parent

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


def load_config() -> dict:
    with open(BUILD_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def rel(path: Path) -> str:
    """PROMO_DIR からの相対パス(POSIX区切り)。ffmpegフィルタ引数のコロン/エスケープ問題を避けるため使用。"""
    return path.resolve().relative_to(PROMO_DIR.resolve()).as_posix()


def run_ffmpeg(args: list[str], *, verbose: bool = False) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner"]
    if not verbose:
        cmd += ["-loglevel", "error"]
    cmd += args
    result = subprocess.run(cmd, cwd=PROMO_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "ffmpegの実行に失敗しました:\n"
            + " ".join(cmd)
            + "\n---stderr---\n"
            + result.stderr
        )


def ensure_shots_json(cfg: dict) -> list[dict]:
    md_path = parse_storyboard.DEFAULT_MD
    shots_path = PROMO_DIR / cfg["paths"]["shots_json"]
    if not shots_path.exists() or md_path.stat().st_mtime > shots_path.stat().st_mtime:
        print("絵コンテを再パースします...")
        shots = parse_storyboard.parse_storyboard(md_path)
        shots_path.parent.mkdir(parents=True, exist_ok=True)
        import json

        shots_path.write_text(
            json.dumps(shots, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return shots
    import json

    return json.loads(shots_path.read_text(encoding="utf-8"))


def find_asset(directory: Path, shot_id: int, exts: set[str]) -> Path | None:
    if not directory.exists():
        return None
    candidates = sorted(
        p for p in directory.glob(f"{shot_id:02d}.*") if p.suffix.lower() in exts
    )
    return candidates[0] if candidates else None


def ensure_fonts_copied(cfg: dict) -> Path:
    fonts_dir = PROMO_DIR / "output" / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    for key in ("primary", "fallback"):
        src = Path(cfg["fonts"][key])
        if src.exists():
            dst = fonts_dir / src.name
            if not dst.exists():
                shutil.copy2(src, dst)
    return fonts_dir


def drawtext_escape_for_file(text: str) -> str:
    # textfile= で読み込むので特殊エスケープはほぼ不要。改行はそのまま実改行でOK。
    return text


def build_segment(
    shot: dict,
    cfg: dict,
    clips_dir: Path,
    tmp_dir: Path,
    width: int,
    height: int,
    fps: int,
) -> Path:
    seg_path = tmp_dir / f"seg_{shot['id']:02d}.mp4"
    duration = max(shot["duration"], 1)
    asset = find_asset(clips_dir, shot["id"], VIDEO_EXTS | IMAGE_EXTS)

    fit_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps={fps},setsar=1,format=yuv420p"
    )

    if asset is not None:
        if asset.suffix.lower() in IMAGE_EXTS:
            in_args = ["-loop", "1", "-t", str(duration), "-i", rel(asset)]
        else:
            in_args = ["-stream_loop", "-1", "-t", str(duration), "-i", rel(asset)]
        run_ffmpeg(
            [*in_args, "-vf", fit_filter, "-an", "-t", str(duration), rel(seg_path)]
        )
    else:
        color = cfg["placeholder_colors"].get(shot["part"], "0x202020")
        # CJK主体のためフォントサイズ相当の文字数で改行(全角文字はおおよそ正方形)
        wrap_width = max(10, int(width / (cfg["placeholder_text_size"] * 1.15)))
        wrapped_visual = "\n".join(textwrap.wrap(shot["visual"], width=wrap_width))
        caption = f"CUT {shot['id']:02d} [{shot['part']}]\n{wrapped_visual}"
        caption_path = tmp_dir / f"ph_text_{shot['id']:02d}.txt"
        caption_path.write_text(drawtext_escape_for_file(caption), encoding="utf-8")

        fonts_dir = ensure_fonts_copied(cfg)
        font_file = fonts_dir / Path(cfg["fonts"]["primary"]).name

        drawtext = (
            f"drawtext=fontfile='{rel(font_file)}':"
            f"textfile='{rel(caption_path)}':"
            f"fontcolor=white:fontsize={cfg['placeholder_text_size']}:"
            "x=(w-text_w)/2:y=(h-text_h)/2:line_spacing=12:"
            "box=1:boxcolor=black@0.35:boxborderw=20"
        )
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:size={width}x{height}:rate={fps}:d={duration}",
                "-vf",
                drawtext,
                "-pix_fmt",
                "yuv420p",
                rel(seg_path),
            ]
        )

    return seg_path


def concat_segments(seg_paths: list[Path], tmp_dir: Path, out_path: Path) -> None:
    concat_list = tmp_dir / "concat.txt"
    lines = [f"file '{p.name}'" for p in seg_paths]
    concat_list.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run_ffmpeg(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            rel(concat_list),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            rel(out_path),
        ]
    )


def ass_timestamp(seconds: float) -> str:
    cs = round(seconds * 100)
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


ALIGNMENT_BY_POSITION = {"bottom": 2, "top": 8, "center": 5}


def build_ass(shots: list[dict], cfg: dict, width: int, height: int, ass_path: Path) -> None:
    telop_cfg = cfg["telop"]
    alignment = ALIGNMENT_BY_POSITION.get(telop_cfg["position"], 2)
    style = (
        "Style: Telop,"
        f"{cfg['fonts']['ass_font_name']},{telop_cfg['font_size']},"
        f"{telop_cfg['color_default']},&H000000FF,{telop_cfg['outline_color']},&H00000000,"
        f"-1,0,0,0,100,100,0,0,1,{telop_cfg['outline_width']},0,{alignment},"
        f"40,40,{telop_cfg['margin_v']},1"
    )

    events = []
    for shot in shots:
        if not shot["has_telop"]:
            continue
        text = "\\N".join(shot["telop_lines"])
        fad = f"{{\\fad({telop_cfg['fade_in_ms']},{telop_cfg['fade_out_ms']})}}"
        start = ass_timestamp(shot["start_sec"])
        end = ass_timestamp(shot["end_sec"])
        events.append(
            f"Dialogue: 0,{start},{end},Telop,,0,0,0,,{fad}{text}"
        )

    content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{chr(10).join(events)}
"""
    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text(content, encoding="utf-8")


def mux_final(
    base_video: Path,
    ass_path: Path,
    fonts_dir: Path,
    shots: list[dict],
    cfg: dict,
    bgm_dir: Path,
    se_dir: Path,
    out_path: Path,
) -> None:
    total_duration = shots[-1]["end_sec"]

    inputs: list[str] = ["-i", rel(base_video)]
    filter_parts = [f"[0:v]ass={rel(ass_path)}:fontsdir={rel(fonts_dir)}[vout]"]

    audio_labels: list[str] = []
    next_input_idx = 1

    bgm_files = sorted(
        p for p in bgm_dir.glob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS
    ) if bgm_dir.exists() else []
    if len(bgm_files) > 1:
        print(f"警告: assets/bgm/ に複数の音源があります。先頭の {bgm_files[0].name} のみ使用します。")
    if bgm_files:
        bgm = bgm_files[0]
        inputs += ["-i", rel(bgm)]
        fade_start = max(total_duration - cfg["bgm_fade_out_sec"], 0)
        filter_parts.append(
            f"[{next_input_idx}:a]atrim=0:{total_duration},"
            f"afade=t=out:st={fade_start}:d={cfg['bgm_fade_out_sec']},"
            f"volume={cfg['bgm_gain_db']}dB[bgm]"
        )
        audio_labels.append("[bgm]")
        next_input_idx += 1

    for shot in shots:
        se_file = find_asset(se_dir, shot["id"], AUDIO_EXTS)
        if se_file is None:
            continue
        inputs += ["-i", rel(se_file)]
        offset_ms = shot["start_sec"] * 1000
        label = f"se{shot['id']}"
        filter_parts.append(f"[{next_input_idx}:a]adelay={offset_ms}|{offset_ms}[{label}]")
        audio_labels.append(f"[{label}]")
        next_input_idx += 1

    map_args = ["-map", "[vout]"]
    if audio_labels:
        filter_parts.append(
            "".join(audio_labels)
            + f"amix=inputs={len(audio_labels)}:duration=first:dropout_transition=0[aout]"
        )
        map_args += ["-map", "[aout]"]
    else:
        print("警告: BGM/SEが1つも見つかりません。無音で書き出します。")
        map_args += ["-an"]

    filter_complex = ";".join(filter_parts)

    run_ffmpeg(
        [
            *inputs,
            "-filter_complex",
            filter_complex,
            *map_args,
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            rel(out_path),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="陣取り紅白戦PVをshots.jsonから合成する")
    parser.add_argument("--preview", action="store_true", help="低解像度・高速ドラフト書き出し")
    parser.add_argument("--verbose", action="store_true", help="ffmpegの詳細ログを表示")
    args = parser.parse_args()

    cfg = load_config()
    shots = ensure_shots_json(cfg)

    width, height = cfg["preview_resolution"] if args.preview else cfg["resolution"]
    fps = cfg["fps"]

    clips_dir = PROMO_DIR / cfg["paths"]["clips_dir"]
    bgm_dir = PROMO_DIR / cfg["paths"]["bgm_dir"]
    se_dir = PROMO_DIR / cfg["paths"]["se_dir"]
    tmp_dir = PROMO_DIR / cfg["paths"]["tmp_dir"]
    tmp_dir.mkdir(parents=True, exist_ok=True)

    missing = [s["id"] for s in shots if find_asset(clips_dir, s["id"], VIDEO_EXTS | IMAGE_EXTS) is None]

    print(f"{len(shots)}カットを合成します(解像度 {width}x{height}, {'プレビュー' if args.preview else '本番'})")
    seg_paths = []
    for shot in shots:
        seg_paths.append(build_segment(shot, cfg, clips_dir, tmp_dir, width, height, fps))
        print(f"  カット{shot['id']:02d} [{shot['part']}] {'素材あり' if shot['id'] not in missing else 'プレースホルダー'}")

    base_video = tmp_dir / "base.mp4"
    concat_segments(seg_paths, tmp_dir, base_video)

    ass_path = PROMO_DIR / cfg["paths"]["ass_file"]
    build_ass(shots, cfg, width, height, ass_path)
    fonts_dir = ensure_fonts_copied(cfg)

    out_key = "preview_out" if args.preview else "final_out"
    out_path = PROMO_DIR / cfg["paths"][out_key]
    mux_final(base_video, ass_path, fonts_dir, shots, cfg, bgm_dir, se_dir, out_path)

    print(f"完成: {out_path}")
    if missing:
        print(f"未投入クリップ(プレースホルダーで代用): {', '.join(f'{i:02d}' for i in missing)}")


if __name__ == "__main__":
    main()
