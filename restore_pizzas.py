"""
消失した pizzas テーブルを、事前に保存されていたピザリストのテキスト
(Desktop/pizza.txt からの手動書き起こし) をもとに復元するワンショットスクリプト。

登録者(added_by)の情報は失われているため 0 を入れている。
削除はサーバー管理者(manage_guild)権限があれば誰でも可能なので実運用上の支障はない。

使い方:
  ローカルDBに対して実行: python restore_pizzas.py
  本番(Railway Volume)に対して実行: railway run python restore_pizzas.py
再実行しても既存IDはスキップされるので安全（冪等）。
"""
import asyncio

import aiosqlite

import config

# 元の pizza_id 順（1〜13）。rating は⭐の数。
PIZZAS = [
    (1, "マルゲリータ", 3,
     "イタリアの王妃の名前が由来になっています。\n"
     "トマトの赤とモッツァレラチーズの白、バジルの緑がイタリアの国旗の色になっていることでも知られています。"),
    (2, "カプリチョーザ", 3,
     "カプリチョーザといえば、有名なイタリアンレストランチェーンを思い出す人も多いと思いますが、"
     "イタリア語では「気まぐれ」を意味し、トッピングは特に決まっていません。"),
    (3, "ペパロニ", 3, ""),
    (4, "カラブレーゼ", 3,
     "トウガラシ料理で有名な南イタリアの街、「カラブリア」のピザです。\n"
     "ピリ辛の味付けが特徴です"),
    (5, "シカゴピザ", 5, "すっごい分厚いピザ\nカロリーの暴力"),
    (6, "ペスカトーレ", 3,
     "イタリア語で漁師を意味するペスカトーレは、その名の通り魚介たっぷりのピザです。"),
    (7, "オルトラーナ", 1,
     "イタリア語で「菜園」を意味するこのピザは、パプリカやナス、ホウレンソウなどの野菜をたっぷり使っています。"),
    (8, "マリナーラ", 1,
     "マリナーラとはイタリア語で「船乗り」の意味。\n"
     "もとはトマトソースとオリーブオイル、オレガノだけで味付けされた、とてもシンプルなピザで、"
     "ナポリの船乗りがよく食べていたそうです。"),
    (9, "パルマ", 1,
     "パルマと言えば、パルマ産生ハムのことで、プロシュートとも呼ばれます。\n"
     "生ハムの塩気とピザの相性は抜群です。"),
    (10, "ビスマルク", 3,
     "半熟卵を真ん中に乗せ、ベーコンとアスパラガス、キノコ類を周りに添えたピザ。"
     "ふんだんに使われたブラックペッパーの香りも良い。"),
    (11, "ディアボラ", 2,
     "ディアボラは「悪魔」のこと。\n\n"
     "チキンが羽を広げた悪魔に見えることや、トウガラシの辛みから悪魔を連想させることなどが、"
     "名前の由来なのだそうです。"),
    (12, "サルモーネ", 3,
     "サルモーネとはイタリア語でサーモンのことです。\n"
     "スモークサーモンを乗せたこのピザは、ルッコラやモッツァレラチーズとの相性が抜群です。"),
    (13, "クアトロ・フォルマッジ", 4,
     "「4種類のチーズ」という意味のこのピザは、その名の通り、4種類のチーズをたっぷり使って作られています。"
     "チーズ好きにはたまらない一品です。"),
]


async def restore():
    print(f"対象DB: {config.DB_PATH}")
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pizzas (
                pizza_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                rating INTEGER DEFAULT 3,
                added_by INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

        inserted, skipped = 0, 0
        for pizza_id, name, rating, description in PIZZAS:
            async with db.execute(
                "SELECT 1 FROM pizzas WHERE pizza_id = ?", (pizza_id,)
            ) as cursor:
                exists = await cursor.fetchone()
            if exists:
                print(f"  ID:{pizza_id} {name} は既に存在するのでスキップ")
                skipped += 1
                continue
            await db.execute(
                "INSERT INTO pizzas (pizza_id, name, description, rating, added_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (pizza_id, name, description, rating, 0),
            )
            print(f"  ID:{pizza_id} {name} を復元しました")
            inserted += 1
        await db.commit()

        # 次のAUTOINCREMENTがID14以降から始まるよう調整
        # （SQLiteはAUTOINCREMENT列への明示的なID挿入時にsqlite_sequenceを自動更新するため、
        #   通常はここで追加の調整は不要）
        async with db.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'pizzas'"
        ) as cursor:
            seq_row = await cursor.fetchone()
        if seq_row is None:
            await db.execute(
                "INSERT INTO sqlite_sequence (name, seq) VALUES ('pizzas', 13)"
            )
        elif seq_row[0] < 13:
            await db.execute(
                "UPDATE sqlite_sequence SET seq = 13 WHERE name = 'pizzas'"
            )
        await db.commit()

    print(f"完了: 復元 {inserted} 件 / スキップ {skipped} 件")


if __name__ == "__main__":
    asyncio.run(restore())
