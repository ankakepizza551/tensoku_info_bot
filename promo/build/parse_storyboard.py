"""絵コンテMarkdown(陣取り紅白戦_PV絵コンテ.md)を output/shots.json に変換する。

対象フォーマット:
  ### PART X. 名前（0:00-0:05）
  | # | 時間 | 画 | テロップ | SE/BGM |
  |---|---|---|---|---|
  | 1 | 0:00-0:02 | ... | ... | ... |

時間表記は「分:秒」ではなく "0:" 接頭辞 + 経過秒(例: 0:70-0:75 は 70秒〜75秒)。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parent
PROMO_DIR = BUILD_DIR.parent
DEFAULT_MD = PROMO_DIR / "陣取り紅白戦_PV絵コンテ.md"
DEFAULT_OUT = PROMO_DIR / "output" / "shots.json"

PART_HEADING_RE = re.compile(r"^### PART\s+([A-Z])\.")
TIME_RANGE_RE = re.compile(r"^0:(\d+)-0:(\d+)$")
NO_TELOP_MARKER = "（テロップなし）"


def parse_time_range(cell: str) -> tuple[int, int]:
    m = TIME_RANGE_RE.match(cell.strip())
    if not m:
        raise ValueError(f"時間表記を解釈できません: {cell!r}")
    return int(m.group(1)), int(m.group(2))


def parse_telop(cell: str) -> tuple[bool, list[str]]:
    cell = cell.strip()
    if cell == NO_TELOP_MARKER:
        return False, []
    lines = [line.strip() for line in cell.split("\\n")]
    lines = [line for line in lines if line]
    return True, lines


def split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def is_separator_row(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-+:?", cell) for cell in cells)


def parse_storyboard(md_path: Path) -> list[dict]:
    lines = md_path.read_text(encoding="utf-8").splitlines()

    shots: list[dict] = []
    current_part: str | None = None
    in_table = False
    header_seen = False

    for raw_line in lines:
        line = raw_line.rstrip()

        heading_match = PART_HEADING_RE.match(line)
        if heading_match:
            current_part = heading_match.group(1)
            in_table = False
            header_seen = False
            continue

        if not line.strip().startswith("|"):
            in_table = False
            header_seen = False
            continue

        if current_part is None:
            continue

        cells = split_row(line)

        if not header_seen:
            # テーブルのヘッダ行 (| # | 時間 | 画 | テロップ | SE/BGM |)
            header_seen = True
            in_table = True
            continue

        if is_separator_row(cells):
            continue

        if not in_table:
            continue

        if len(cells) != 5:
            raise ValueError(f"想定外の列数です({len(cells)}列): {line!r}")

        cut_id_str, time_range, visual, telop_cell, se_bgm = cells
        cut_id = int(cut_id_str)
        start_sec, end_sec = parse_time_range(time_range)
        has_telop, telop_lines = parse_telop(telop_cell)

        shots.append(
            {
                "id": cut_id,
                "part": current_part,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "duration": end_sec - start_sec,
                "visual": visual,
                "has_telop": has_telop,
                "telop_lines": telop_lines,
                "se_bgm_note": se_bgm,
            }
        )

    shots.sort(key=lambda s: s["id"])
    return shots


def main() -> None:
    md_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MD
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT

    if not md_path.exists():
        raise SystemExit(f"絵コンテファイルが見つかりません: {md_path}")

    shots = parse_storyboard(md_path)
    if not shots:
        raise SystemExit("カットを1件も抽出できませんでした。表フォーマットを確認してください。")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(shots, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    total_duration = shots[-1]["end_sec"]
    print(f"{len(shots)}カットを抽出しました(合計 {total_duration}秒) -> {out_path}")


if __name__ == "__main__":
    main()
