"""カードBAN10先で使うカード一覧の読み込み（JSON / CSV）と書き出し

取り込める形式は2つです。

■ JSON
{
  "system": [ {"name": "システムカード名", "cost": 1}, ... ],
  "characters": {
    "博麗霊夢": {
      "skill": [ {"name": "スキルカード名"}, ... ],
      "spell": [ {"name": "霊符「夢想封印」", "cost": 2}, ... ]
    },
    ...
  }
}
カードは {"name": ..., "cost": ...} の代わりに、名前だけの文字列でも構いません。

■ CSV（1行目は見出し。区分は system / skill / spell、または システム / スキル / スペル）
区分,キャラ,カード名,コスト
system,,システムカード名,1
skill,博麗霊夢,スキルカード名,
spell,博麗霊夢,霊符「夢想封印」,2
"""
import csv
import io
import json

CATEGORIES = ("system", "skill", "spell")
CATEGORY_LABELS = {"system": "システム", "skill": "スキル", "spell": "スペル"}
_CATEGORY_ALIASES = {
    "system": "system", "システム": "system", "システムカード": "system", "sys": "system",
    "skill": "skill", "スキル": "skill", "スキルカード": "skill",
    "spell": "spell", "スペル": "spell", "スペルカード": "spell",
}

# Discordのセレクトメニューの値の上限が100文字のため、カードの識別子もこの長さに収める
MAX_KEY_LENGTH = 100


class CardImportError(ValueError):
    """取り込みデータの形式エラー（メッセージはそのままユーザーに見せる）"""


def make_card_key(category: str, character: str, name: str) -> str:
    return f"{category}|{character}|{name}"


def _card(category: str, character: str, name, cost) -> dict:
    name = str(name).strip()
    if not name:
        raise CardImportError(f"カード名が空の行があります（{CATEGORY_LABELS[category]} / {character or '共通'}）")
    if cost in (None, ""):
        cost_value = None
    else:
        try:
            cost_value = int(cost)
        except (TypeError, ValueError):
            raise CardImportError(f"「{name}」のコスト `{cost}` が数字ではありません")
    key = make_card_key(category, character, name)
    if len(key) > MAX_KEY_LENGTH:
        raise CardImportError(f"「{name}」のカード名が長すぎます")
    return {"card_key": key, "category": category, "character": character, "name": name, "cost": cost_value}


def _entry(category: str, character: str, item) -> dict:
    if isinstance(item, dict):
        return _card(category, character, item.get("name", ""), item.get("cost"))
    return _card(category, character, item, None)


def _parse_json(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise CardImportError(f"JSONとして読めません（{e.lineno}行目付近）")
    if not isinstance(data, dict):
        raise CardImportError("JSONの一番外側は {\"system\": [...], \"characters\": {...}} の形にしてください")

    cards = [_entry("system", "", item) for item in data.get("system", [])]
    characters = data.get("characters", {})
    if not isinstance(characters, dict):
        raise CardImportError("\"characters\" はキャラ名をキーにしたオブジェクトにしてください")
    for character, groups in characters.items():
        if not isinstance(groups, dict):
            raise CardImportError(f"「{character}」の中身は {{\"skill\": [...], \"spell\": [...]}} にしてください")
        for category in ("skill", "spell"):
            cards.extend(_entry(category, character, item) for item in groups.get(category, []))
    return cards


def _parse_csv(text: str) -> list[dict]:
    rows = list(csv.reader(io.StringIO(text)))
    cards = []
    for line_no, row in enumerate(rows, start=1):
        if not row or all(not cell.strip() for cell in row):
            continue
        head = row[0].strip()
        if line_no == 1 and head.lower() not in _CATEGORY_ALIASES:
            continue  # 見出し行
        row = [cell.strip() for cell in row] + ["", "", "", ""]
        category = _CATEGORY_ALIASES.get(row[0].lower())
        if category is None:
            raise CardImportError(f"CSV {line_no}行目: 区分 `{row[0]}` は system / skill / spell のどれかにしてください")
        character = "" if category == "system" else row[1]
        if category != "system" and not character:
            raise CardImportError(f"CSV {line_no}行目: スキル・スペルカードにはキャラ名が必要です")
        cards.append(_card(category, character, row[2], row[3]))
    return cards


def parse_cards(text: str, filename: str, known_characters: list[str]) -> list[dict]:
    """ファイルの中身をカードのリストにする。形式やキャラ名がおかしければ CardImportError"""
    text = text.lstrip("﻿")  # Excelで保存したCSVのBOMを外す
    if filename.lower().endswith(".csv"):
        cards = _parse_csv(text)
    elif filename.lower().endswith(".json") or text.lstrip().startswith("{"):
        cards = _parse_json(text)
    else:
        cards = _parse_csv(text)

    if not cards:
        raise CardImportError("カードが1枚もありません")

    unknown = sorted({c["character"] for c in cards if c["character"] and c["character"] not in known_characters})
    if unknown:
        raise CardImportError(
            "キャラ名が登録済みのキャラと一致しません: " + "、".join(unknown)
            + "\n使えるキャラ名: " + "、".join(known_characters)
        )

    seen = set()
    duplicates = []
    for c in cards:
        if c["card_key"] in seen:
            duplicates.append(c["name"])
        seen.add(c["card_key"])
    if duplicates:
        raise CardImportError("同じカードが2回以上あります: " + "、".join(sorted(set(duplicates))))
    return cards


def cards_to_json(cards: list[dict], characters: list[str]) -> str:
    """カード一覧を取り込みと同じJSON形式にする。カードが無いキャラも空の枠で出すので、ひな形にも使える"""
    data = {"system": [], "characters": {ch: {"skill": [], "spell": []} for ch in characters}}
    for c in cards:
        item = {"name": c["name"]}
        if c.get("cost") is not None:
            item["cost"] = c["cost"]
        if c["category"] == "system":
            data["system"].append(item)
        else:
            data["characters"].setdefault(c["character"], {"skill": [], "spell": []})[c["category"]].append(item)
    return json.dumps(data, ensure_ascii=False, indent=2)


def card_label(card: dict) -> str:
    """一覧やセレクトメニューでの表示名"""
    if card.get("cost") is not None:
        return f"{card['name']}（{card['cost']}）"
    return card["name"]
