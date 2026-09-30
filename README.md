<p align="center">
  <img src="images/logo.png" alt="SearXNG Next Logo" width="300">
</p>



# SearXNG for Windows Next 🚀

**GenAIフレンドリーな検索体験を、Windowsネイティブ環境で。**

このプロジェクトは、Windows環境でSearXNGを最適に動作させつつ、LLM（大規模言語モデル）やAPIワークフローから利用しやすい**軽量・高速な検索結果取得**を実現することを目的としたフォークリポジトリです。

---

##  主な特徴

-  Windows Native: 組み込みPython環境により、DockerなしでWindows上で直接動作。
-  **AI-First WebUI (`/ai` & ネイティブ統合)**: 外部CDN・フレームワーク不要の超軽量「AI Search & Context Studio」と、既存の `simple` テーマ上でのインライン本文抽出・ワンクリックMarkdown/RAGコピー機能を搭載。
-  GenAI Optimized: LLMのトークン消費を抑える専用の `json_lite` フォーマットおよび HTTP `/deep_search` エンドポイントを搭載。
- High-Quality Engines: Bing, DuckDuckGo, Mojeekなどの信頼性の高いエンジンを標準で最適化。
- Auto-Sync Architecture: `searxng/searxng` 本家の最新コードを追従しつつ、Windows固有のパッチを自動適用。常に最新の状態に。
- Secure & Local: ローカルホストでの動作に特化したセキュアなデフォルト設定。

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
- **AI Search & Context Studio (AIファースト専用UI)**: [http://127.0.0.1:8888/ai](http://127.0.0.1:8888/ai)
- **Classic SearXNG (AI拡張バー付き)**: [http://127.0.0.1:8888](http://127.0.0.1:8888)

### 3. 動作確認 (Testing)
以下のコマンドを実行して、特に `json_lite` 形式や `/deep_search` のレスポンスが正しく返ってくるか確認できます。

**PowerShell:**
```powershell
Invoke-RestMethod "http://127.0.0.1:8888/search?q=SearXNG&format=json_lite" | ConvertTo-Json -Depth 5
Invoke-RestMethod "http://127.0.0.1:8888/deep_search?q=SearXNG&count=3" | ConvertTo-Json -Depth 5
```

**curl:**
```bash
curl -G "http://127.0.0.1:8888/search" --data-urlencode "q=SearXNG" --data-urlencode "format=json_lite"
curl -G "http://127.0.0.1:8888/deep_search" --data-urlencode "q=SearXNG" --data-urlencode "format=markdown"
```

### 4. キャッシュのクリーンアップ (軽量化)
蓄積した Python バイトコード（`__pycache__`）や一時キャッシュを一括消去し、約 25〜30MB のディスク容量をワンクリックで解放できます。
```powershell
PowerShell -File .\tools\clean-cache.ps1
```

---

## 🖥️ AI-First WebUI (`/ai` & Classic 統合)

本プロジェクトでは、人間とAIエージェントの双方にとって直感的かつ超軽量（外部JS/CSS依存ゼロ・単一ファイル完結）な2つのUI体験を提供します。検索ロジック（`json_lite` 高速スニペット・`/scrape` 本文抽出・`Agentic Deep Search`）は単一の統合パイプライン（`tools/agentic_search.py`）に集約されています。

### 1. AI Search & Context Studio (`/ai` または `/next`)
ブラウザで `http://127.0.0.1:8888/ai` を開くと、**単一の統合検索＆本文抽出バー**を備えたAIコンテキスト生成ワークスペースが起動します。
- **🔍 入力自動判別 (Keyword vs URL)**:
  - **キーワードや質問を入力**: 選択した `Mode / Depth`（`Deep: Advanced` / `Deep: Code & Docs` / `Basic` / `Fast: json_lite`）で統合検索を実行。
  - **URL (`https://...`) を貼り付け**: 自動的に **URL 本文抽出モード** に切り替わり、SSRF保護付き本文抽出（`trafilatura`）と任意キーワードによる BM25 重要段落ハイライト抽出を実行。
- **🤖 Agent & MCP Hub モード**: Claude Code / Cursor / OpenCode 用の設定JSONやCLIコマンドを、稼働中サーバーのURLに合わせて自動生成・ワンクリックコピー。
- **コンテキスト予算＆ワンクリック出力**: 推定トークン数のプログレスバー表示、`📋 AI用Markdownをコピー`、`💬 RAGプロンプト形式でコピー`（情報源引用ルール付きプロンプト）、`{ } JSONをコピー`、`💾 .md 保存` を完備。

### 2. 標準 `simple` テーマへのプログレッシブ拡張 (`/`・`/search`)
従来のSearXNG画面（`/` および `/search`）もそのまま利用でき、ホーム画面の `⚡ AI Search & Scrape Studio` ボタンや検索結果画面上部のスリムな **AI Toolkit** と各検索結果カードのアクションボタン（`📄 本文抽出`・`📋 引用コピー`）によって、ページ遷移なしで本文プレビューやLLM向けMarkdownコピーが可能です。

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
