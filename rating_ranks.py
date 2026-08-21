"""サーバー独自のランク・レート定義（上級:天人 / 中級:妖怪 / 初級:人間）"""

RANK_TIERS = [
    {
        "name": "天人・極", "reading": "てんにん・きょく", "min_rating": 2000,
        "color": 0xFF2A4B,
        "description": "神域・最上位勢（全鯖トップクラス・大会上位常連）",
    },
    {
        "name": "天人・熟", "reading": "てんにん・じゅく", "min_rating": 1900,
        "color": 0xFF6B35,
        "description": "猛者（上位層の中でも頭一つ抜けた存在）",
    },
    {
        "name": "天人・初", "reading": "てんにん・しょ", "min_rating": 1800,
        "color": 0xFFAA00,
        "description": "上級者の入口（基礎～応用が完璧に仕上がっている）",
    },
    {
        "name": "妖怪・極", "reading": "ようかい・きょく", "min_rating": 1700,
        "color": 0x9B51E0,
        "description": "中級上位（メインキャラの強みがかなり出せる）",
    },
    {
        "name": "妖怪・熟", "reading": "ようかい・じゅく", "min_rating": 1600,
        "color": 0x56CCF2,
        "description": "中級中位（勝率が安定し始める）",
    },
    {
        "name": "妖怪・初", "reading": "ようかい・しょ", "min_rating": 1500,
        "color": 0x2D9CDB,
        "description": "中央値～標準（対戦の基本を理解し実戦に慣れた層）",
    },
    {
        "name": "人間・極", "reading": "にんげん・きょく", "min_rating": 1400,
        "color": 0x27AE60,
        "description": "初級上位（脱・初心者を目指す段階）",
    },
    {
        "name": "人間・熟", "reading": "にんげん・じゅく", "min_rating": 1300,
        "color": 0x6FCF97,
        "description": "初級中位（コンボや基本的な立ち回りを練習中）",
    },
    {
        "name": "人間・初", "reading": "にんげん・しょ", "min_rating": 0,
        "color": 0xA8E6CF,
        "description": "初学者・ビギナー（天則を始めたばかり・復帰勢など）",
    },
]

# 上から順（レートの高い順）に並んでいる前提のロール名一覧
RANK_ROLE_NAMES = [tier["name"] for tier in RANK_TIERS]


def get_rank_info(rating: float) -> dict:
    """レーティングに対応するランク定義（名前・カラー・概要など）を返す"""
    for tier in RANK_TIERS:
        if rating >= tier["min_rating"]:
            return tier
    return RANK_TIERS[-1]


def get_rank(rating: float) -> str:
    """レーティングルームのランク名を返す（後方互換用の簡易版）"""
    return get_rank_info(rating)["name"]
