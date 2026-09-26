"""公開サイト向けの読み取り専用API。

個人を特定できる情報（ユーザー名・ID・個別のレート）は返さず、集計値だけを返す。
サイト(Cloudflare Pages)からブラウザで直接取得できるよう、CORSを許可する。
"""
import logging
import os

from aiohttp import web

from database import db_manager
from rating_ranks import RANK_TIERS, get_rank

logger = logging.getLogger("TensokuMatchBot")

# 許可するオリジン（カンマ区切り）。未設定なら集計値のみなので全許可。
_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("PUBLIC_API_ORIGINS", "*").split(",") if o.strip()
]


def _cors_headers(request: web.Request) -> dict:
    origin = request.headers.get("Origin", "")
    if "*" in _ALLOWED_ORIGINS:
        allow = "*"
    elif origin in _ALLOWED_ORIGINS:
        allow = origin
    else:
        return {}
    return {
        "Access-Control-Allow-Origin": allow,
        "Vary": "Origin",
        "Cache-Control": "public, max-age=60",
    }


async def handle_stats(request: web.Request) -> web.Response:
    try:
        ratings = await db_manager.get_rated_player_ratings()
        chars = await db_manager.get_main_character_counts()
    except Exception as e:
        logger.error(f"公開API stats 取得失敗: {e}")
        return web.json_response({"error": "取得に失敗しました。"}, status=500, headers=_cors_headers(request))

    counts = {tier["name"]: 0 for tier in RANK_TIERS}
    for rating in ratings:
        counts[get_rank(rating)] += 1

    body = {
        "ranks": {
            "total": len(ratings),
            "tiers": [
                {"name": t["name"], "min_rating": t["min_rating"], "count": counts[t["name"]]}
                for t in RANK_TIERS
            ],
        },
        "main_characters": {
            "total": sum(n for _, n in chars),
            "characters": [{"name": name, "count": n} for name, n in chars],
        },
    }
    return web.json_response(body, headers=_cors_headers(request))


def add_routes(app: web.Application) -> None:
    app.router.add_get("/api/public/stats", handle_stats)
