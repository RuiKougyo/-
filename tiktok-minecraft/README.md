# TikTok × Minecraft ギミック連動ツール

TikTokのライブ配信で**ギフト・フォロー・いいね・コメント**が届くと、
**Minecraftの中でギミック（モブ召喚・TNT・雷・アイテム配布など）が自動で動く**ツールです。

- 配信が始まるのを自動で待ち、始まったら自動で接続します。配信が終われば次の配信を待ちます
- **ツールを起動したまま放置**できます（接続が切れても、Minecraftサーバーが落ちても自動で復帰します）
- どのギフトで何が起きるかは、設定ファイル（`config.yaml`）で自由に変えられます
- パソコンにPythonなどを入れる必要はありません。**exeファイルと設定ファイルだけ**で動きます

```
 視聴者がギフトを送る
        │
        ▼
 TikTokライブ ──(受信)──▶ TikTokMinecraft.exe ──(RCON)──▶ Minecraftサーバー
                          ギフト → コマンドに変換           ゾンビ召喚！ TNT！ 雷！
```

> 📌 **この手順書の読み方**
> 手順1〜5を順番に進めてください。初めてなら1時間ほどかかります。

---

## 目次

1. [Minecraftサーバーを用意する](#手順1-minecraftサーバーを用意する)
2. [RCONを有効にする](#手順2-rconを有効にする)
3. [設定ファイルを書く](#手順3-設定ファイルを書く)
4. [テストモードで動作確認する](#手順4-テストモードで動作確認する)
5. [配信して放置する](#手順5-配信して放置する)
6. [ギミックの作り方（設定の詳しい説明）](#ギミックの作り方設定の詳しい説明)
7. [完全放置のコツ](#完全放置のコツ)
8. [よくあるトラブル](#よくあるトラブル)
9. [ご利用上の注意](#ご利用上の注意)
10. [開発者向け情報](#開発者向け情報)

---

## 準備するもの

| もの | 説明 |
|---|---|
| Windows 10 / 11 のパソコン | ツール・Minecraft・配信ソフトを動かします |
| Minecraft **Java版** | 統合版（スイッチ・スマホ版など）には対応していません |
| TikTokでライブ配信ができるアカウント | ギフトを受け取るには、TikTokの年齢・条件を満たしている必要があります |
| 配信ソフト | TikTok LIVE Studio、または OBS など |

### 届いたファイル

```
TikTokMinecraft.exe  … ツール本体
config.sample.yaml   … 設定ファイルのひな形
start.bat            … 本番スタート（ダブルクリックで起動）
test.bat             … テストモード
check.bat            … Minecraftへの接続チェック
README.md            … この手順書
```

分かりやすい場所（例：`ドキュメント\TikTok連動`）にまとめて置いてください。

---

## 手順1. Minecraftサーバーを用意する

このツールは、Minecraftの「サーバー」にコマンドを送ってギミックを動かします。
**ふつうのシングルプレイでは動かない**ので、自分のパソコンでサーバーを立てて、そこに自分で入って遊びます。
（サーバーといっても、同じパソコンの中で動かすだけです。お金はかかりません）

おすすめは軽くて安定している **Paper** というサーバーです。

1. Java（Minecraftサーバー用）を入れる
   最新のMinecraftには **Java 21** が必要です。「Adoptium Temurin 21」で検索してインストールしてください
2. https://papermc.io/downloads/paper から、遊びたいバージョンの `paper-○○.jar` をダウンロード
3. `ドキュメント\mcserver` のようなフォルダを作り、jarファイルを入れる
4. 同じフォルダに `start-server.bat` というファイルを作り、メモ帳で次のように書いて保存
   ```bat
   java -Xmx4G -jar paper-○○.jar nogui
   pause
   ```
   （`paper-○○.jar` は実際のファイル名に置き換えてください）
5. `start-server.bat` をダブルクリック → 1回目は止まるので、できた `eula.txt` を開いて
   `eula=false` を `eula=true` に変えて保存し、もう一度起動
6. Minecraftを起動 → マルチプレイ → サーバーを追加 → アドレスに `localhost` と入れて参加

---

## 手順2. RCONを有効にする

RCON（アールコン）は、外部からサーバーにコマンドを送るための仕組みです。

1. サーバーを止める（サーバーの黒い画面で `stop` と入力）
2. サーバーフォルダの `server.properties` をメモ帳で開き、次の3行を探して書き換える
   ```properties
   enable-rcon=true
   rcon.port=25575
   rcon.password=好きなパスワード（英数字で長めに）
   ```
3. 保存して、サーバーをもう一度起動

> ⚠️ **ルーターで 25575番ポートを開放しないでください。**
> 開放すると、パスワードを知った他人がサーバーを自由に操作できてしまいます。
> このツールは同じパソコンの中で通信するので、開放は不要です。

---

## 手順3. 設定ファイルを書く

1. `TikTokMinecraft.exe` を1回ダブルクリックすると、同じフォルダに `config.yaml` が作られます
   （`config.sample.yaml` をコピーして `config.yaml` に名前を変えてもOK）
2. `config.yaml` を右クリック →「プログラムから開く」→「メモ帳」
3. 最低限、次の3か所を書き換えて保存します

```yaml
tiktok:
  username: "your_tiktok_id"          # ← あなたのTikTok ID（@の後ろ）

minecraft:
  password: "ここにRCONのパスワード"   # ← 手順2で決めた rcon.password
  player: "Steve"                     # ← あなたのMinecraftのプレイヤー名
```

ほかの項目（どのギフトで何が起きるか）は、最初はそのままで大丈夫です。
あとから [ギミックの作り方](#ギミックの作り方設定の詳しい説明) を見て好きに変えてください。

---

## 手順4. テストモードで動作確認する

配信する前に、「ギフトが来たふり」をして、Minecraftでちゃんと動くか確かめます。

1. Minecraftサーバーを起動し、Minecraftで参加しておく
2. `check.bat` をダブルクリック
   → 「Minecraftサーバーに接続できました！」と出て、ゲーム内に「接続テストOK！」と表示されれば成功
3. `test.bat` をダブルクリックし、黒い画面に次のように入力してEnter

| 入力 | 意味 |
|---|---|
| `gift Rose 5` | バラが5個届いたふり（ゾンビが5体出る） |
| `gift Lion 1 29999` | 29999コインのギフトが1個届いたふり（コイン数で決まるギミックの確認） |
| `follow` | フォローされたふり |
| `like 100` | いいねが100届いたふり |
| `comment ジャンプ` | 「ジャンプ」とコメントされたふり |
| `quit` | 終了 |

> 💡 Minecraftを起動せずに試したいときは、`TikTokMinecraft.exe --test --dry-run` で
> 「送るはずのコマンド」を画面に表示するだけのモードになります。

---

## 手順5. 配信して放置する

1. Minecraftサーバーを起動し、Minecraftで参加する
2. 配信ソフト（TikTok LIVE Studio など）で、Minecraftの画面を映してTikTokライブを開始
3. `start.bat` をダブルクリック

あとは放置でOKです。画面にはこのように表示されます。

```
[情報] @your_tiktok_id は今は配信していません。配信が始まるまで 60 秒ごとに確認して待ちます…
[情報] TikTokライブ（@your_tiktok_id）に接続しました！ギフトを待っています。
[情報] 🎁 たろう さんから「Rose」×3
[情報] ➕ フォロー：はなこ さん
```

- **先にツールを起動しておいても大丈夫**です。配信が始まると自動でつながります
- 配信が終わると、自動で「次の配信待ち」に戻ります
- 終了するときは、黒い画面で `Ctrl` + `C` を押すか、画面を閉じてください
- 動作の記録は `logs\live.log` に残ります（1MBごとに切り替え、5つまで保存）

---

## ギミックの作り方（設定の詳しい説明）

### ギフトごとのギミック

```yaml
gifts:
  - name: "バラ → ゾンビ召喚"     # ログに出る名前（自由に付けてOK）
    gift: ["Rose"]                # ギフトの名前（英語）またはギフトID
    repeat: true                  # 個数ぶん繰り返す（バラ5個 → 5回）
    commands:
      - 'execute at {player} run summon zombie ~ ~ ~3 {Tags:["tiktok"]}'
```

- **上から順に確認し、最初に当てはまったものだけ**が動きます
- ギフトの名前は英語で届きます（例：`Rose`、`TikTok`、`Finger Heart`）。
  名前が分からないギフトは、一度受け取るとログに次のように出るので、それを書き写してください
  ```
  設定にないギフトです: 名前「Galaxy」 ID 11046（1000コイン）。
  ```
- 名前の代わりに**コイン数の範囲**でも決められます。名前を書いていないギフトに便利です
  ```yaml
  - name: "100〜499コイン → 雷"
    min_coins: 100
    max_coins: 499
    repeat: false
    commands:
      - 'execute at {player} run summon lightning_bolt'
  ```
- `times: 3` と書くと、1個あたり3回動きます（バラ2個 → 6回）
- どれにも当てはまらないギフトは `unknown_gift` のコマンドが動きます
- `gift_announce` に書いたコマンドは、**どのギフトでも最初に1回**動きます（お礼表示など）

### コマンドに差し込める文字

| 書き方 | 置き換わるもの |
|---|---|
| `{player}` | 設定したあなたのプレイヤー名 |
| `{nickname}` | ギフト等を送ってくれた人の表示名 |
| `{username}` | その人のTikTok ID |
| `{gift}` / `{count}` | ギフトの名前 / 個数 |
| `{coins}` / `{total_coins}` | ギフト1個のコイン数 / コイン数×個数 |
| `{n}` | 繰り返しの何回目か（1, 2, 3…） |
| `{comment}` | コメントの内容 |
| `{likes}` | いいねの合計数 |

視聴者の名前に `"` などの記号が入っていても、コマンドが壊れないよう自動で処理します。

### 特別なコマンド `wait`

```yaml
commands:
  - 'title @a title {"text":"3"}'
  - 'wait 1'
  - 'title @a title {"text":"2"}'
```

`wait 秒数` で次のコマンドまで待てます（最大60秒）。
※待っている間はほかのギフトのコマンドも順番待ちになります。長い `wait` は控えめに。

### ギフト以外

| 項目 | いつ動くか | 便利な設定 |
|---|---|---|
| `follow` | フォローされたとき | `once_per_user: true`（同じ人は配信ごとに1回だけ） |
| `share` | シェアされたとき | `cooldown_seconds: 60`（同じ人は60秒に1回まで） |
| `likes` | いいね合計が `every` を超えるごと | `every: 100` |
| `join` | 視聴者が入室したとき（初期設定は無効） | `global_cooldown_seconds: 30` |
| `subscribe` | サブスク登録されたとき | |
| `comments` | `keywords` の言葉を含むコメント | `cooldown_seconds` / `global_cooldown_seconds` |
| `timers` | 配信中、`every_minutes` 分ごと | 案内表示・お掃除などに |

使わないものは `enabled: false` にするか、まるごと消してください。

### その他の設定

| 設定 | 意味 |
|---|---|
| `gift_mode: immediate` | 連打されたギフトを1個ごとにすぐ動かす（おすすめ） |
| `gift_mode: streak_end` | 連打が終わってから、まとめて個数分動かす |
| `minecraft → commands_per_second` | 1秒あたりに送るコマンド数の上限。サーバーが重ければ小さく |
| `minecraft → max_repeat` | 1回のギフトで繰り返す上限（バラ999個で暴走しないように） |
| `minecraft → max_queue` | 順番待ちできるコマンド数。超えた分は捨てて、ログに注意を出します |

> 💡 コマンドが間違っていると、ログに「Minecraftでエラーになりました」と、
> Minecraftからの返事つきで表示されます（同じ間違いは1回だけ表示）。

---

## 完全放置のコツ

長時間放置しても止まらないように、次の設定をおすすめします。

**Minecraft側（サーバーの黒い画面、またはゲーム内で `/` を付けて入力）**

```
gamerule keepInventory true        … 死んでもアイテムがなくならない
gamerule doImmediateRespawn true   … 死んだら自動ですぐ復活（放置中に止まらない）
gamerule mobGriefing false         … クリーパーやTNTで地形がこわれにくくなる（TNTは除く）
```

- 召喚したモブには `{Tags:["tiktok"]}` を付けておき、`timers` の「お掃除」（`kill @e[tag=tiktok]`）で
  定期的に消すと、モブが増えすぎてサーバーが重くなるのを防げます（サンプル設定に入っています）
- Minecraftの画面から別のウィンドウに切り替えるとポーズ画面になります。
  `F3` + `P` を押すと「切り替えてもポーズしない」設定になります
- Windowsの「設定 → システム → 電源」で、**スリープを「なし」**にしてください
- Minecraftサーバーが落ちても、ツールは復旧を待って自動でつなぎ直します（その間のコマンドは順番待ちで保持）

---

## よくあるトラブル

| 症状 | 原因と対処 |
|---|---|
| 「Minecraftサーバーに接続できません」 | サーバーが起動していない、または `server.properties` の `enable-rcon=true` を保存後にサーバーを再起動していない |
| 「RCONのパスワードが違います」 | `config.yaml` の `password` と `server.properties` の `rcon.password` を同じにする |
| 「設定のプレイヤー名が見つかりません」 | `player:` のつづり（大文字・小文字）を確認。Minecraftでサーバーに参加しているかも確認 |
| ギフトが来たのに何も起きない | ログの「設定にないギフトです」を確認し、`gifts` に名前を追加。`unknown_gift` を書いておけば必ず何か動きます |
| 「TikTokのユーザーが見つかりません」 | `username` に @ の後ろのIDを正しく書く（表示名ではありません） |
| 「接続の回数制限にかかりました」 | しばらく待つと自動で再試行します。頻発する場合は `check_interval_seconds` を大きくするか、Euler Stream のAPIキーを `sign_api_key` に設定 |
| 配信中なのに「配信していません」のまま | 配信開始直後は数十秒〜1分ほど遅れて検知されることがあります |
| 設定ファイルのエラーで起動しない | 表示された行の字下げ（空白の数）や `:` の後の空白を確認。タブ文字は使えません |
| 日本語の表示が文字化けする | `config.yaml` を「UTF-8」で保存し直す（メモ帳の「名前を付けて保存」で文字コードを選べます） |

---

## ご利用上の注意

- TikTokライブの受信には、有志が作った非公式ライブラリ「[TikTokLive](https://github.com/isaackogan/TikTokLive)」を使っています。
  **TikTokの仕様変更で突然動かなくなる可能性があります。** その場合は新しいバージョンのツールを使ってください
- 受信には、TikTokLiveが利用する外部の署名サービス（Euler Stream）を経由します
- 放置配信・ギフト連動の配信が、**TikTokのコミュニティガイドラインや LIVE のルールに合っているか**は、
  ご自身で最新の内容を確認してください
- Minecraftサーバーの改変・配信については、Minecraftの利用規約（EULA）・コミュニティ規約に従ってください

---

## 開発者向け情報

### 構成

```
tiktok-minecraft/
├── run.py                  … 入口
├── tiktok_mc/
│   ├── main.py             … 起動・テストモード・接続チェック
│   ├── config.py           … 設定の読み込みとチェック
│   ├── tiktok_source.py    … TikTokライブへの自動接続・再接続、ギフト連打の個数計算
│   ├── rules.py            … 出来事 → コマンドへの変換（差し込み文字・クールダウン・いいね集計）
│   ├── executor.py         … コマンドの順番待ち・送信数制限・Minecraft復旧待ち
│   ├── rcon.py             … RCONクライアント（標準ライブラリのみ）
│   └── events.py / log_setup.py / paths.py
├── tests/                  … pytest（RCONは擬似サーバーで通信まで確認）
├── config.sample.yaml
├── tiktok_minecraft.spec   … PyInstaller設定
├── build.bat               … exe作成（Windows）
└── launchers/              … 配布用の起動bat
```

### Pythonで直接動かす

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest -q
python run.py --test --dry-run
```

### exeを作る

Python 3.10以上が入ったWindowsで `build.bat` をダブルクリックすると、
テスト実行のあと `release` フォルダに配布一式がそろいます。
