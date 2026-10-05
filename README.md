<p align="center">
  <img src="images/logo.png" alt="SearXNG Next Logo" width="300">
</p>



# SearXNG for Windows Next 🚀

[![CI Test](https://github.com/TopiTech/SearXNGforWindowsNext/actions/workflows/ci.yml/badge.svg)](https://github.com/TopiTech/SearXNGforWindowsNext/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6.svg?logo=windows)](README.md)
[![Python: 3.11](https://img.shields.io/badge/python-3.11-3776AB.svg?logo=python)](pyproject.toml)

**GenAIフレンドリーな検索体験を、Windowsネイティブ環境で。**

このプロジェクトは、Windows環境でSearXNGを最適に動作させつつ、LLM（大規模言語モデル）やAPIワークフローから利用しやすい**軽量・高速な検索結果取得**を実現することを目的としたフォークリポジトリです。

---

##  主な特徴

- ⚡ **Windows Native**: 組み込みPython環境により、DockerなしでWindows上で直接動作。
- 🧠 **GenAI Retrieval API (`/api/retrieval` & `json_ai`)**: LLM や AI エージェントが根拠・引用として利用できる高品質な検索結果と見出し単位の根拠パッセージ（Evidence Passages）を提供する検索基盤。Reciprocal Rank Fusion、多言語 BM25 字句再ランキング、決定論的クエリ展開、SSRF 防御を統合。
- 🎨 **AI-First Dedicated WebUI (`/`)**: 従来のレガシーClassic UIを完全廃止し、AI Search & Context Studioに一本化。4つの専用モード（AI Deep Search / Classic 検索 / Agent & MCP Hub / 設定）を統合し、全エンジンの稼働状況や信頼性をリアルタイムに監視・設定可能。
- 📦 **GenAI Optimized**: LLMのトークン消費を抑える専用の `json_lite`、新世代 `json_ai` / `evidence_json` フォーマット、および HTTP `/deep_search` エンドポイントを搭載。
- 🔍 **High-Quality Engines**: Bing, DuckDuckGo, Mojeekなどの信頼性の高いエンジンを標準で最適化。
- 🔄 **Auto-Sync Architecture**: `searxng/searxng` 本家の最新コードを追従しつつ、Windows固有のパッチを自動適用。レガシーUIの誤復活を阻止する多層防御を完備。
- 🛡️ **Secure & Local**: ローカルホストでの動作に特化したセキュアなデフォルト設定。SSRF防御およびプロンプトインジェクション検知スキャナを内蔵。

---

##  クイックスタート

### 1. セットアップ
リポジトリをダウンロード(クローン)後、まずは依存パッケージをインストールします。

```powershell
# PowerShellで実行
.\tools\install-requirements.ps1
```

### 2. 起動
`SearXNG for Windows.bat` を実行します。起動後、ブラウザで以下にアクセスできます：
- **AI-First Search & Context Studio (統合UI)**: [http://127.0.0.1:8888](http://127.0.0.1:8888)（または `/ai`）
  - **AI Deep Search**: BM25 + 並列スクレイピング + トークン推定 + RAGプロンプト生成 + Markdownプレビュー
  - **Classic 検索**: カテゴリタブ・時間フィルタ・ファビコン・画像グリッド・1クリックAI深掘り
  - **Agent & MCP Hub**: Claude Code, Cursor, OpenCode 連携設定・ワンクリックコピー
  - **設定**: 全260+エンジンのリアルタイム稼働状態（Online/Suspended/Disabled）、個別Pingテスト、未保存変更通知

### 3. 動作確認 (Testing)
以下のコマンドを実行して、特に `json_lite` 形式や `/deep_search` のレスポンスが正しく返ってくるか確認できます。

**PowerShell:**
```powershell
# 1. 新世代 GenAI Retrieval API (根拠パッセージ付き)
Invoke-RestMethod "http://127.0.0.1:8888/api/retrieval?q=SearXNG&mode=balanced" | ConvertTo-Json -Depth 6

# 2. 軽量 json_lite 形式
Invoke-RestMethod "http://127.0.0.1:8888/search?q=SearXNG&format=json_lite" | ConvertTo-Json -Depth 5

# 3. Deep Search 形式
Invoke-RestMethod "http://127.0.0.1:8888/deep_search?q=SearXNG&count=3" | ConvertTo-Json -Depth 5
```

**curl:**
```bash
# GenAI 向け構造化レスポンス (json_ai)
curl -G "http://127.0.0.1:8888/api/retrieval" --data-urlencode "q=SearXNG" --data-urlencode "mode=balanced"

# 既存 json_lite 形式 (完全後方互換)
curl -G "http://127.0.0.1:8888/search" --data-urlencode "q=SearXNG" --data-urlencode "format=json_lite"

# Markdown 形式
curl -G "http://127.0.0.1:8888/deep_search" --data-urlencode "q=SearXNG" --data-urlencode "format=markdown"
```

### 4. キャッシュのクリーンアップと容量最適化 (軽量化)
蓄積した Python バイトコード（`__pycache__`）、不要な翻訳ソース（`.po`）、ソースマップ（`*.map`）を一括消去し、約 25〜50MB+ のディスク容量を解放できます。

```powershell
# 標準クリーンアップ (安全: バイトコード, .po, .map, .tmp を削除)
PowerShell -File .\tools\clean-cache.ps1

# ディープクリーンアップ (Babel の未使用言語パック約25MB & pipキャッシュを削除)
PowerShell -File .\tools\clean-cache.ps1 -Deep

# 開発用ツール削除 (型検査ツール pyrefly 32MB をアンインストール)
PowerShell -File .\tools\clean-cache.ps1 -UninstallDev

# Git リポジトリの最適化
PowerShell -File .\tools\clean-cache.ps1 -GitGc
```

---

## 🧠 高品質 Retrieval API (GenAI / Agent / MCP 向け)

SearXNG for Windows Next は、AI モデル自身が回答を生成するための **信頼性の高い検索結果と根拠パッセージ（Evidence Passages）** を提供する専用の検索基盤です。

詳細なアーキテクチャや仕様は **[docs/RETRIEVAL_API.md](docs/RETRIEVAL_API.md)** をご覧ください。

### 検索モード (`mode`)

| モード | スクレイピング | 特徴・用途 |
|---|:---:|---|
| `fast` | なし (0件) | 低レイテンシ重視（スニペット・正規化・RRF・BM25 のみ） |
| `balanced` (推奨) | 上位3件 | 速度と根拠パッセージのバランス。決定論的クエリ展開1件 |
| `deep` | 上位6件 | 複数観点クエリ展開（最大2件）、複数ラウンド探索 |

### CLI からの利用
```powershell
# 根拠パッセージ付き Retrieval
.\python\python.exe tools\searxng_cli.py retrieval "FastAPI lifespan"

# 高速モード (JSON 出力)
.\python\python.exe tools\searxng_cli.py retrieval "python asyncio" --mode fast --json
```

### MCP (Model Context Protocol) ツール
- `searxng_retrieval`: 構造化された根拠パッセージを返す推奨ツール
- `searxng_search`: `mode="balanced"` に対応した汎用検索ツール
- `searxng_scrape`: SSRF 保護付き本文抽出ツール

---

## 🖥️ AI-First Dedicated WebUI (`/`)

SearXNG for Windows Next では、旧来の Jinja2 `simple` テーマ画面を完全に廃止し、**AI Search & Context Studio** を単一のプライマリWebインターフェースとして一本化しました。外部CDNや重量級JSフレームワークに一切依存せず（完全ローカル完結・ゼロ外部依存）、洗練されたタイポグラフィとインライン SVG アイコン、キーボードショートカット、リアルタイム支援機能を備えたモダンなワークスペースを提供します。

### 4つの専用モード

1. **AI Deep Search (`mode=deep`)**:
   - ワンストップでメタ検索＋並列スクレイピング＋多言語BM25パッセージ抽出を実行。
   - 推定トークン数メーター、AI用Markdown、RAGプロンプト生成、JSONエクスポート、`.md` ファイル保存をワンクリックで提供。
   - Context Inspector に軽量 Markdown プレビュー機能を統合（HTML/Raw/Markdown タブ切り替え可能）。
2. **Classic 検索 (`mode=classic`)**:
   - 従来の検索エンジンの軽快さを好むユーザー向けの高速・軽量1カラム検索モード。
   - カテゴリタブ（IT, 科学, ニュース, ソーシャル等）、時間フィルタ（全期間, 1日, 1週間, 1か月, 1年）、ドメイン横ファビコン、エンジン識別バッジ、ページネーションを完備。
   - 画像カテゴリ (`images`) 選択時はレスポンシブな画像ギャラリーグリッド表示に自動切り替え。
   - 各検索結果カードからワンクリックで「AIで深掘り」を実行でき、瞬時に Deep Search モードへ連携可能。
3. **Agent & MCP Hub (`mode=agent`)**:
   - Claude Code / Cursor / Windsurf / OpenCode / CLI 向けの設定JSONや登録コマンドを、現在のサーバーホストURLに合わせて自動生成・ワンクリックコピー。
4. **設定ダッシュボード (`mode=settings`)**:
   - 全260以上のエンジンのリアルタイム稼働状態（Online / Suspended / Disabled）、応答時間(ms)、信頼性(%)を一目で把握できる一覧グリッド。
   - カテゴリ別フィルタリング、エンジン名リアルタイム絞り込み、個別Ping/テスト実行ボタン、個別トグルスイッチおよび一括「全有効 / 全無効 / デフォルトに戻す」ボタンを搭載。
   - 変更がある場合は画面下部に「未保存の変更があります」フローティングバーが表示され、ページ離脱時の確認（`beforeunload`）も完備。
   - 設定は `disabled_engines` / `enabled_engines` Cookie および `localStorage` に保存され、ブラウザとAPIリクエストの双方で永続化。

### 先進的な UX / 操作性機能

- **インライン SVG & クリーンデザイン**: 絵文字に頼らない幾何学的かつ直感的な軽量インライン SVG アイコンセットと視認性の高いタイポグラフィを採用。
- **SearXNG Autocompleter 連携**: 検索窓入力時に `/autocompleter` API からリアルタイムで候補を取得し、ドロップダウン表示（キーボード上下キーで選択可能）。
- **直近の検索履歴**: 過去の検索クエリをローカルストレージに保持し、検索窓下にクイック再検索チップとして表示（ワンクリックで再実行・個別/一括消去）。
- **キーボードナビゲーション**:
  - `j` / `k` (または `↓` / `↑`): 検索結果カードの上下移動
  - `Enter`: 選択中カードのリンクを開く
  - `c`: 選択中カードのタイトル＋URLを Markdown 形式でクリップボードへコピー
  - `Alt + 1` 〜 `4`: モード切替（AI Deep Search / Classic / Agent Hub / 設定）
  - `/`: 検索入力フォーカス
  - `Esc`: サジェストやモーダルを閉じる
- **スケルトンローディング & レースコンディション制御**: 検索中にパルスアニメーション付きプレースホルダーを表示。先行する未完了リクエストは `AbortController` で安全に自動キャンセル。
- **URL & ブラウザ履歴同期**: モード切替や検索クエリが URL（`?mode=...&q=...`）に同期され、ブラウザの「戻る」「進む」に完全対応。
- **モジュール化アーキテクチャ**: `tools/webui/` 配下に CSS, HTML, JS を整理・モジュール分離し、保守性と堅牢性を両立。単一ファイル配布（`webui_next.py`）への自動バンドル機構も内蔵。

### 既存URLからの自動ルーティング & アップストリーム防御

- **ブラウザリクエストの自動遷移**:
  - `GET /` → AI Search & Context Studio
  - `GET /search?q=...` → `GET /?q=...`（HTMLアクセス時は自動的にAIスタジオへ302リダイレクト）
  - `GET /preferences` → `GET /?mode=settings`
  - `GET /about` → `GET /?mode=agent`
- **API互換性の100%保証**:
  - `GET /search?q=...&format=json` や `format=json_lite`、`format=csv`、HTTPヘッダー `Accept: application/json` を含むリクエストは、リダイレクトされず従来のAPIハンドラーに透過的に引き渡されます。
- **5層のアップストリーム誤復活防止アーキテクチャ**:
  - `webapp_ai_webui` パッチを `CRITICAL` に指定し、アップストリーム同期時にルーティング注入が失敗した場合は即座に同期・起動を中断。
  - `app.before_request` による最優先インターセプト、`app.view_functions` による第2防衛層、テンプレートレベルのクライアントサイド・リダイレクトガード、`sync-upstream.ps1` での自動テスト検証、起動バッチのパッチ先行適用により、本家コードの更新によって旧UIが意図せず復活することを構造的に防ぎます。

---

##  GenAI / LLM での活用例 (統合検索パイプライン)

従来バラバラだった **`json_lite`（高速スニペット検索）**・**`/scrape`（URL本文抽出）**・**`Agentic Deep Search`（並列本文抽出＋BM25ハイライト）** は、共通の統合エンジン（`execute_unified_search` / `/deep_search` / `/api/search`）に統合されつつ、すべての既存エンドポイントとの100%後方互換性を維持しています。

| モード / エンドポイント | 特徴・用途 |
|---|---|
| **Unified Deep Search** (`/deep_search`, `/api/search`) | 1リクエストで「メタ検索 → ドメイン権威スコアリング → 並列本文抽出 → BM25ハイライト抽出 → トークン予算パッキング」を実行。`depth=fast` 指定で `json_lite` 相当の高速検索、`mode=scrape`（またはURL指定）で単一URL本文抽出＋BM25ハイライトも実行可能。 |
| **Fast Search (`json_lite`)** (`/search?format=json_lite`) | 通常のJSONに含まれる膨大なメタデータを削ぎ落とし、タイトル・URL・スニペット・エンジン名のみを最速で返却。 |
| **URL Scrape** (`/scrape`, `/api/scrape_analyze`) | 特定URLのWebページ本文のみを `trafilatura` でクリーン抽出（DNSピニング＆SSRF防御付き）。`/api/scrape_analyze` では `?q=` 指定によるBM25ハイライト抽出にも対応。 |

### `json_lite` フォーマット
通常のJSONレスポンスに含まれる膨大なメタデータを削ぎ落とし、AIが必要とする情報（タイトル・URL・内容）のみを返します。

**リクエスト例:**
```http
GET http://127.0.0.1:8888/search?q=SearXNG&format=json_lite
```

**レスポンス例:**
```json
{
  "query": "SearXNG",
  "results": [
    {
      "title": "SearXNG Documentation",
      "url": "https://docs.searxng.org/",
      "content": "SearXNG is a free internet metasearch engine..."
    }
  ]
}
```

### `scrape` エンドポイント (本文抽出)
検索結果のスニペットだけでは情報が不足する場合、特定のURLを指定してそのページの**本文のみ**を抽出して取得できます。精度向上のため `trafilatura` ライブラリを使用しています。なおスクレイピングに関しては節度を持った利用を心がけるようにお願い致します。~~SearXNG自体スクレイピングという話はありますが....~~

**リクエスト例:**
```http
GET http://127.0.0.1:8888/scrape?url=https://example.com/article
```

**レスポンス例:**
```json
{
  "url": "https://example.com/article",
  "content": "ここに抽出された本文が表示されます..."
}
```



### ⚡ Agentic Deep Search / Unified Search (`/deep_search` & `/api/search`)
**1 回のリクエストで検索・並列スクレイピング・BM25ハイライト抽出・ドメイン評価を完結**させる統合検索エンドポイントです。CLI・MCP だけでなく、HTTP API（`GET/POST /deep_search` または `/api/search`）および WebUI（`/ai`）から直接呼び出せます。
- **One-Pass 完結 & URL 自動判別**: キーワードを渡せば深層検索、URL（`https://...`）を渡せば本文抽出＋BM25ハイライトを自動実行。
- **Smart Highlighting**: 1万文字の長文から、クエリに最も関連するパラグラフ（200〜400文字）をBM25スコアリングでピンポイント抽出。
- **Domain Authority & Anti-SEO Spam**: 公式ドキュメント（Python, MDN, GitHub等）を自動加点し、低品質コピペファーム・広告まとめサイトを自動除外・ペナルティ。
- **Token Budgeting**: 指定したトークン予算（`max_tokens`）内に収まるよう重要度順に構造化パッキング。

**HTTP API での実行例 (JSON または Markdown 直接取得):**
```http
GET http://127.0.0.1:8888/deep_search?q=FastAPI+lifespan&count=3&max_tokens=3000
GET http://127.0.0.1:8888/deep_search?q=FastAPI+lifespan&count=3&format=markdown
GET http://127.0.0.1:8888/api/search?q=FastAPI+lifespan&depth=fast
```

**CLI での実行例:**
```bash
# Deep Search (並列本文抽出 + BM25 ハイライト)
python tools/searxng_cli.py deep "FastAPI lifespan context manager syntax" -n 3

# 統合 search コマンドでも --mode deep や URL 自動判別に対応
python tools/searxng_cli.py search "FastAPI lifespan" --mode deep -d code
python tools/searxng_cli.py search "https://docs.searxng.org"
```

---

### 🤖 コーディングエージェント連携 (OpenCode, Claude Code, Cursor, Codex など)

SearXNG for Windows Next は **OpenCode**, **Claude Code**, **Cursor**, **Windsurf**, **Cline**, **OpenAI Codex CLI**, **Aider** 等の AI コーディングエージェントから極めて簡単に呼び出すことができます。

詳細なエージェント別設定手順やトラブルシューティングは [docs/CODING_AGENTS.md](docs/CODING_AGENTS.md) を参照してください。

#### 1. MCP (Model Context Protocol) サーバーとして呼び出す
エージェント設定ファイルに登録するだけで、以下のツールが利用可能になります：
- `searxng_deep_search`: **【推奨】** Exa/Tavily スタイルのワンパス深層検索（並列本文抽出＋BM25ハイライト＋ドメイン重み付け）
- `searxng_search`: 統合Web検索（既定は高速 `json_lite`、`mode="deep"` や `search_depth` 指定で深層検索、URL入力で自動本文抽出に対応）
- `searxng_scrape`: 特定URLの本文抽出（`query` 指定でBM25ハイライト抽出にも対応）
- `searxng_health`: SearXNG サーバーの稼働確認

- **OpenCode (`opencode.json`):**
  ```json
  {
    "mcp": {
      "searxng": {
        "type": "local",
        "command": ["python", "tools/mcp_server.py"],
        "enabled": true
      }
    }
  }
  ```

- **Claude Code (CLI):**
  ```bash
  claude mcp add searxng -- python tools/mcp_server.py
  ```

- **Cursor / Windsurf / Claude Desktop (`.cursor/mcp.json` 等):**
  ```json
  {
    "mcpServers": {
      "searxng": {
        "command": "python",
        "args": ["tools/mcp_server.py"],
        "env": {
          "SEARXNG_BASE_URL": "http://127.0.0.1:8888"
        }
      }
    }
  }
  ```

#### 2. コマンドライン / Codex / ターミナルから呼び出す
MCP 非対応のエージェントやスクリプトからでも、付属の CLI ツールで簡単に検索・本文抽出を行えます。

```bash
# Web 検索 (既定: json_lite 高速スニペット / --mode deep で深層検索 / URL 渡すと自動スクレイプ)
python tools/searxng_cli.py search "FastAPI lifespan events" -n 5
python tools/searxng_cli.py search "FastAPI lifespan events" --mode deep -n 3

# Web ページの本文抽出 (-q で BM25 ハイライト抽出も可)
python tools/searxng_cli.py scrape "https://docs.searxng.org" --max-chars 3000 -q "json_lite"

# サーバー稼働確認 (Windows バッチラッパー)
tools\searxng.bat health
```



### Open WebUI での活用例 (Tool として登録)

Open WebUI を使用している場合、この SearXNG フォークの「検索（json_lite）」および「スクレイピング（scrape）」機能をツールとして登録することで、AI が必要に応じて Web 検索と本文抽出を組み合わせて実行できるようになります。なおこの機能に関しては未テストであり、想定していた動作結果が得られない可能性があります。

#### 1. ツールの作成
Open WebUI のメニューから **「Workspace」→「Tools」→「Create Tool」** を開き、以下の内容を入力します。

- **Name**: `SearXNG Toolkit`
- **Description**: `Search the web and extract website content using SearXNG.`
- **Python Code**:

```python
import requests


class Tools:
    def __init__(self):
        pass

    def search_web(self, query: str) -> str:
        """
        指定されたキーワードでウェブ検索を行い、最新の情報を取得します。
        :param query: 検索キーワード
        """
        # このフォーク専用の json_lite フォーマットを指定
        try:
            response = requests.get(
                "http://localhost:8888/search",
                params={"q": query, "format": "json_lite"},
                timeout=10,
            )
            response.raise_for_status()
            response.json()  # Validate JSON format
            return response.text
        except requests.exceptions.Timeout:
            return "SearXNG への接続タイムアウト: リクエストが10秒以内に完了しませんでした"
        except requests.exceptions.HTTPError as e:
            return f"SearXNG HTTP エラー: {e.response.status_code}"
        except requests.exceptions.JSONDecodeError:
            return "SearXNG レスポンス形式エラー: 無効なJSON形式です"
        except Exception as e:
            return f"SearXNG への接続エラー: {str(e)[:100]}"

    def get_website_content(self, url: str) -> str:
        """
        指定されたURLのウェブページから本文を抽出して取得します。
        検索結果のスニペットだけでは情報が不足している場合や、詳細が必要な場合に使用してください。
        :param url: 取得したいウェブページのURL
        """
        # 今回実装した scrape エンドポイントを使用
        try:
            response = requests.get(
                "http://localhost:8888/scrape",
                params={"url": url},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("content", "本文の抽出に失敗しました。")
            if not content:
                return "抽出可能な本文が見つかりませんでした。"
            return content
        except requests.exceptions.Timeout:
            return f"スクレイピングタイムアウト: {url} からのレスポンスが15秒以内に得られませんでした"
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                return f"ブロック済み: プライベートIP、ループバック、またはファイルスキームです"
            elif e.response.status_code == 422:
                return f"本文抽出失敗: {url} から抽出可能な内容がありません"
            else:
                return f"スクレイピング HTTP エラー: {e.response.status_code}"
        except requests.exceptions.JSONDecodeError:
            return "スクレイピングレスポンス形式エラー: 無効なJSON形式です"
        except Exception as e:
            return f"スクレイピングエラー: {str(e)[:100]}"
```

#### 2. モデルへの適用
作成したツールを保存した後、チャット画面のモデル設定（または「Workspace」→「Models」）から、このツールを有効にします。これで、AI が「検索が必要だ」と判断した際に、トークン効率の極めて高い `json_lite` 形式で情報を取得できるようになります。

---

##  構成ファイル

- **`SearXNG for Windows.bat`**: メインの起動スクリプト。
- **`tools/webui_next.py`**: 超軽量 AI-First WebUI (`/ai`)、クラシックテーマ拡張アセット (`/ai/embed.*`)、および `/deep_search`・`/api/scrape_analyze`・`/api/ai_info` エンドポイント実装。
- **`tools/agentic_search.py`**: BM25 ハイライト抽出・ドメイン権威性評価・トークン予算パッキングを行う Deep Search エンジン。
- **`tools/mcp_server.py`**: AI コーディングエージェント用 MCP (Model Context Protocol) stdio サーバー。
- **`tools/searxng_cli.py`**: ターミナルおよびエージェント向けコマンドライン検索・スクレイピングツール。
- **`tools/searxng.bat`**: Windows 用 CLI 実行ラッパー。
- **`docs/CODING_AGENTS.md`**: 各種コーディングエージェント連携の詳細マニュアル。
- **`config/agent_templates/`**: OpenCode, Cursor 等のエージェント設定テンプレート集。
- **`config/settings.yml.example`**: 追跡されるテンプレート。初回起動時に `config/settings.yml` へコピーされる。
- **`config/settings.yml`**: ユーザー設定（エンジン、ポート、フォーマットなど）。`.gitignore` 対象のため自由に編集可能。
- **`config/secret.key`**: Flask の `secret_key` のみを保存するローカルファイル。`.gitignore` 対象。削除すると次回起動時に新しいキーが生成される。
- **`tools/sync-upstream.ps1`**: 本家リポジトリとの同期およびパッチ適用。
- **`python/`**: ポータブルな組み込みPython環境。

> 🔐 **セキュリティメモ**: `secret_key` は `config/secret.key` に保存され、起動時に `SEARXNG_SECRET` 環境変数として Granian に渡されます。`config/settings.yml` 内の `secret_key` 行はプレースホルダであり、実際には使用されません。これにより、ローテーションのたびに `settings.yml` をコミットする必要がなくなり、誤って秘密鍵をリポジトリに含めてしまうことを防ぎます。

---

##  メンテナンスと同期

GitHub Actions（`.github/workflows/upstream-sync.yml`）により、本家のアップデートが週次で自動チェックされます。同期プロセスでは以下の処理が行われます：

1. `searxng/searxng` の最新ソースを取得。
2. Windows互換性およびGenAI向け機能のパッチを再適用。
3. `requirements.txt` の変更を検知し、ユーザーに通知。
4. **ユーザーの `settings.yml` は上書きされません。**

---

## 🛠 高度なカスタマイズ

### 検索結果の文量をさらに増やしたい場合（オプション）

> [!WARNING]
> `python\Lib\site-packages\searx\` 配下は上流同期のたびに上書きされ、本リポジトリのパッチが再適用されます。直接手編集した内容は次回同期で失われます。永続化したい変更は `tools/apply-patches.py` のパッチ関数として実装してください（詳細は `DEVELOPMENT.md` の Patch System 章を参照）。

`json_lite` 形式で取得できる情報量をさらに増やしたい場合は、以下の手順でコードを書き換えることができます。

#### 方法1: スニペットの結合（コードの書き換え）
複数のエンジンから同じURLの結果が返ってきた際、それぞれのスニペットを結合して情報量を増やすことができます。

1. `python\Lib\site-packages\searx\webutils.py` を開きます。
2. `get_json_lite_response` 関数内の `results` 生成部分を以下のように書き換えます（※これは一例です）：

```python
        'results': [
            {
                'title': _.title,
                'url': _.url,
                # 'content' だけでなく 'metadata' なども含める例
                'content': (_.content + " " + getattr(_, 'metadata', '')).strip(),
                'source': ", ".join(_.engines) # 全ての取得元を表示
            } for _ in rc.get_ordered_results()
        ]
```

#### 方法2: 特定のエンジンを有効化する
以下のエンジンは、比較的長文のスニペットや詳細なインフォボックスを返す傾向があります。`config\settings.yml` でこれらを有効化（`disabled: false`）することを検討してください。
- `wikipedia`: インフォボックスに詳細な要約が含まれます。
- `google`: 他のエンジンに比べてスニペットが長くなる傾向があります。
- `bing`: 安定して詳細な情報を返します。

> [!WARNING]
> 文量を増やしすぎると、LLM のトークン消費量が増大し、レスポンス速度の低下やコスト増につながる可能性があるため、ご利用のモデルに合わせて調整してください。

---

## 🤝 コントリビューション & 開発

本プロジェクトへの機能改善・バグ報告・ドキュメント修正などのコントリビューションを歓迎します！
Windows ネイティブ環境固有のパッチシステムや開発フローについては、以下のドキュメントをご参照ください。

- 📖 **[開発ガイド (DEVELOPMENT.md)](DEVELOPMENT.md)**: 開発環境のセットアップとアーキテクチャ
- 🤝 **[コントリビューションガイド (CONTRIBUTING.md)](CONTRIBUTING.md)**: PR作成ルール・テスト実行・パッチ作成
- 🧩 **[Windows パッチ仕様 (docs/WINDOWS_PATCHES.md)](docs/WINDOWS_PATCHES.md)**: 適用パッチ一覧とアップストリーム同期方針
- 📜 **[行動規範 (CODE_OF_CONDUCT.md)](CODE_OF_CONDUCT.md)**: コミュニティ規範
- 🛡️ **[セキュリティポリシー (SECURITY.md)](SECURITY.md)**: 脆弱性報告手順・SSRF 防御仕様

---

## 📜 ライセンス

このプロジェクトはフォーク元に準じ **GNU Affero General Public License v3 (AGPL-3.0)** の下で公開されています。
詳細は [LICENSE](LICENSE) ファイルを参照してください。

---

## 🔒 誤って secret_key をコミット・プッシュしてしまった場合の対処法

`config/settings.yml` やその他のファイルに実際の `secret_key` を記述したまま誤ってコミットまたはプッシュしてしまった場合は、セキュリティ確保のため以下の手順で対処してください。

### 1. まだリモートに push していない場合（ローカルのみ）

コミットを取り消すか、コミット内容を修正して安全な状態に戻します。

```bash
# 直前のコミットを取り消して変更をワークツリーに残す
git reset --soft HEAD~1

# または設定ファイルから secret_key を除去・修正した上でコミットを上書き
git add config/settings.yml
git commit --amend --no-edit
```

### 2. すでにリモート（GitHub等）へ push してしまった場合

公開リポジトリ等へプッシュしてしまった場合は、後から修正コミットを追加してもコミット履歴にキーが残ってしまいます。**「キーの失効・再生成」** と **「Git 履歴からの完全パージ」** を行ってください。

#### ステップ1: secret_key の再生成（最優先）
漏洩したキーは侵害されたものとみなし、即座に無効化して新しいキーを発行してください。
本プロジェクトでは `config/secret.key`（`.gitignore` 対象）にキーが保存される仕様のため、該当ファイルを削除して再生成します（次回サーバー起動時またはツール実行時に自動で安全な32バイトのランダムキーが生成されます）。

```powershell
# 方法A: 既存の secret.key を削除（次回起動時に自動再生成）
Remove-Item "config\secret.key" -ErrorAction SilentlyContinue

# または 方法B: ツールを実行して即座に新しいキーを生成
.\python\python.exe tools\ensure-secret-key.py
```

#### ステップ2: Git 履歴からキーを完全に消去（git-filter-repo）
過去のコミット履歴から該当の文字列を安全なダミー値（`CHANGE_ME` 等）に置換・パージします。

```bash
# 1. 作業用のフレッシュな clone を作成
git clone <repository-url> searxng-cleanup
cd searxng-cleanup

# 2. 置換ルールファイルを作成（リポジトリ外または一時ファイル）
# フォーマット: 漏洩した実際の文字列==>置換後の文字列
echo "漏洩した実際のキー文字列==>CHANGE_ME" > replace.txt

# 3. 履歴全体を一括書き換え
git-filter-repo --force --replace-text replace.txt

# 4. 履歴から漏洩キーが消えたことを確認（検索結果が空であればOK）
git log -S "漏洩した実際のキー文字列" --all

# 5. リモートへ強制プッシュ
git remote add origin <repository-url>
git push --force --tags --all
```

> [!WARNING]
> **共同作業者への周知**
> 強制プッシュ（`git push --force`）を行うと、既存のコミットハッシュ（SHA）がすべて変更されます。リポジトリをクローンしている他のメンバーは、`git fetch origin && git reset --hard origin/main` などでローカル環境を再同期する必要があります。
