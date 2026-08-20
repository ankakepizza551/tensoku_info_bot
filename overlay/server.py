"""陣取りゲームの陣地マップを配信画面(OBSブラウザソース)向けに配信するWebサーバー。

discord.py が依存する aiohttp を流用し、Botと同じイベントループ上で動かす。
Railwayでは「Networking」からこのサービスの公開ドメインを発行し、
そのURLをOBSのブラウザソースに指定して使う。
"""
import logging
import os

from aiohttp import web

from database import db_manager

logger = logging.getLogger("TensokuMatchBot")

TEAM_LABELS = ["Aチーム", "Bチーム", "Cチーム", "Dチーム"]
TEAM_COLORS_HEX = ["#e74c3c", "#3498db", "#f1c40f", "#2ecc71"]

OVERLAY_TOKEN = os.getenv("TERRITORY_OVERLAY_TOKEN", "").strip()

_PAGE_HTML = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>陣取りマップ</title>
<style>
  html, body { margin: 0; padding: 0; background: transparent; }
  body {
    font-family: "Yu Gothic UI", "Hiragino Sans", sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 16px;
  }
  #grid {
    display: grid;
    gap: 4px;
  }
  .cell {
    width: 48px;
    height: 48px;
    border-radius: 6px;
    background: #555;
    box-shadow: 0 2px 4px rgba(0,0,0,0.4);
    transition: background-color 0.4s ease;
  }
  #legend {
    display: flex;
    gap: 14px;
    background: rgba(0,0,0,0.55);
    padding: 8px 16px;
    border-radius: 10px;
    color: #fff;
    font-size: 18px;
    font-weight: bold;
    text-shadow: 0 1px 2px rgba(0,0,0,0.6);
  }
  .legend-item { display: flex; align-items: center; gap: 6px; }
  .dot { width: 14px; height: 14px; border-radius: 50%; }
  #status {
    color: #fff;
    background: rgba(0,0,0,0.55);
    padding: 4px 12px;
    border-radius: 8px;
    font-size: 13px;
  }
</style>
</head>
<body>
  <div id="grid"></div>
  <div id="legend"></div>
  <div id="status">読み込み中...</div>
<script>
  const params = new URLSearchParams(location.search);
  const guildId = params.get("guild_id");
  const token = params.get("token") || "";
  const gridEl = document.getElementById("grid");
  const legendEl = document.getElementById("legend");
  const statusEl = document.getElementById("status");
  let cellEls = [];
  let currentSide = 0;

  async function refresh() {
    try {
      const url = `/territory/api?guild_id=${encodeURIComponent(guildId)}&token=${encodeURIComponent(token)}`;
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) {
        statusEl.textContent = `取得エラー (${res.status})`;
        return;
      }
      const data = await res.json();

      if (data.side !== currentSide) {
        currentSide = data.side;
        gridEl.style.gridTemplateColumns = `repeat(${currentSide}, 48px)`;
        gridEl.innerHTML = "";
        cellEls = data.cells.map(() => {
          const div = document.createElement("div");
          div.className = "cell";
          gridEl.appendChild(div);
          return div;
        });
      }

      data.cells.forEach((teamIndex, i) => {
        cellEls[i].style.backgroundColor = data.team_colors[teamIndex] || "#555";
      });

      legendEl.innerHTML = data.teams.map(t =>
        `<div class="legend-item"><span class="dot" style="background:${t.color}"></span>${t.label} ${t.count}マス</div>`
      ).join("");

      statusEl.textContent = "";
    } catch (e) {
      statusEl.textContent = "接続エラー";
    }
  }

  refresh();
  setInterval(refresh, 3000);
</script>
</body>
</html>
"""


def _check_token(request: web.Request) -> bool:
    if not OVERLAY_TOKEN:
        return True
    return request.query.get("token", "") == OVERLAY_TOKEN


async def handle_page(request: web.Request) -> web.Response:
    if not request.query.get("guild_id"):
        return web.Response(status=400, text="guild_id クエリパラメータが必要です。")
    return web.Response(text=_PAGE_HTML, content_type="text/html")


async def handle_api(request: web.Request) -> web.Response:
    if not _check_token(request):
        return web.Response(status=403, text="token が一致しません。")

    guild_id_raw = request.query.get("guild_id")
    if not guild_id_raw or not guild_id_raw.isdigit():
        return web.json_response({"error": "guild_id が不正です。"}, status=400)

    guild_id = int(guild_id_raw)
    grid = await db_manager.get_territory_grid(guild_id)
    if not grid:
        return web.json_response({"error": "陣地マップが未初期化です。"}, status=404)

    cells = [g["team_index"] for g in grid]
    side = int(round(len(cells) ** 0.5))
    n_teams = max(cells) + 1

    counts = [0] * n_teams
    for v in cells:
        counts[v] += 1

    teams = [
        {"label": TEAM_LABELS[i], "color": TEAM_COLORS_HEX[i % len(TEAM_COLORS_HEX)], "count": counts[i]}
        for i in range(n_teams)
    ]

    return web.json_response({
        "side": side,
        "cells": cells,
        "team_colors": TEAM_COLORS_HEX,
        "teams": teams,
    })


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/territory", handle_page)
    app.router.add_get("/territory/api", handle_api)
    return app


async def start_overlay_server() -> web.AppRunner:
    port = int(os.getenv("PORT", "8080"))
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"陣取りマップ配信用サーバーを起動しました (port={port})")
    return runner
