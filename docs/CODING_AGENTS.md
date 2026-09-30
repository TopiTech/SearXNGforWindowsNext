# コーディングエージェント連携ガイド (Coding Agents Guide)

本ドキュメントでは、**SearXNG for Windows Next** を各種 AI コーディングエージェント（**OpenCode**, **Claude Code**, **Cursor**, **Windsurf**, **Cline / Roo Code**, **OpenAI Codex CLI**, **Aider** 等）から呼び出すための設定方法と活用手順を詳しく解説します。

---

## 🎯 概要とメリット

SearXNG for Windows Next は、ローカル環境で動作するプライバシー重視のメタ検索エンジンです。本フォークには AI エージェント向けに最適化された以下の機能が標準搭載されています：

1. **`json_lite` 形式による超軽量 Web 検索**:
   LLM の入力コンテキスト（トークン）を最小限に抑えつつ、検索結果（タイトル・URL・スニペット・情報元）を提供します。
2. **`/scrape` エンドポイントによる本文抽出**:
   検索スニペットだけでは情報が不足する場合、指定した Web ページの本文のみをクリーンに抽出します。
3. **SSRF 防御機構**:
   エージェントが誤ってローカルネットワークや機密メタデータアドレス（AWS/Azure の `169.254.169.254` 等）にアクセスするのを自動遮断します。
4. **ゼロ依存の MCP サーバー (`tools/mcp_server.py`)**:
   Model Context Protocol (MCP 2024-11-05) に準拠し、追加パッケージのインストールなしで瞬時に起動します。
5. **スタンドアロン CLI ツール (`tools/searxng_cli.py` / `tools/searxng.bat`)**:
   MCP 非対応の環境やターミナル型エージェントでも、コマンドラインから直接検索・本文抽出が可能です。

---

## 🛠 前提条件

1. **SearXNG サーバーの起動**:
   プロジェクトルートにある `SearXNG for Windows.bat` を実行し、サーバー（`http://127.0.0.1:8888`）を起動しておきます。
2. **接続確認**:
   以下のコマンドを実行し、正常に応答が返ることを確認します。
   ```powershell
   .\tools\searxng.bat health
   # 成功時: ✅ SearXNG サーバー稼働中 (http://127.0.0.1:8888): OK
   ```

---

## 🤖 エージェント別設定手順

### 1. OpenCode での設定

[OpenCode](https://opencode.ai) は MCP を標準サポートしています。プロジェクトルートの `opencode.json` またはグローバル設定（`~/.config/opencode/opencode.json`）に設定を追加します。

#### プロジェクトローカル設定 (`opencode.json`)
プロジェクトルートに `opencode.json` を配置します（テンプレート: `config/agent_templates/opencode.json`）。

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "searxng": {
      "type": "local",
      "command": [
        "python",
        "tools/mcp_server.py"
      ],
      "environment": {
        "SEARXNG_BASE_URL": "http://127.0.0.1:8888"
      },
      "enabled": true
    }
  }
}
```

> 💡 **Windows 環境での注意**:
> パスを通していない環境の場合は `"command"` 内の `"python"` を `"python/python.exe"` または絶対パスに書き換えてください。

---

### 2. Claude Code での設定

Anthropic の [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) では、`claude mcp add` コマンドで簡単に追加できます。

```bash
# プロジェクトルートで実行する場合
claude mcp add searxng -- python tools/mcp_server.py

# または絶対パスで指定
claude mcp add searxng -- "C:/path/to/SearXNGforWindowsNext/python/python.exe" "C:/path/to/SearXNGforWindowsNext/tools/mcp_server.py"
```

登録後、Claude Code のセッション内で以下のように自動的に Web 検索や本文抽出が呼び出されます：
```
> 最新の FastAPI でライフスパンイベントを定義する書き方を Web で調べて実装して
```

---

### 3. Cursor での設定

[Cursor](https://www.cursor.com/) では、プロジェクト内の `.cursor/mcp.json` または Cursor の設定画面（**Settings → Features → MCP**）から追加します。

#### `.cursor/mcp.json` の設定
プロジェクトルートに `.cursor/mcp.json` を作成（または既存ファイルに追加）します：

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

Cursor の設定画面で `searxng` の横に緑色のランプ（Tools: 3）が表示されれば準備完了です。

---

### 4. Windsurf / Codeium での設定

Windsurf の MCP 設定ファイル（`~/.codeium/windsurf/mcp_config.json`）に以下を追加します：

```json
{
  "mcpServers": {
    "searxng": {
      "command": "python",
      "args": ["C:/path/to/SearXNGforWindowsNext/tools/mcp_server.py"],
      "env": {
        "SEARXNG_BASE_URL": "http://127.0.0.1:8888"
      }
    }
  }
}
```

---

### 5. Cline / Roo Code での設定

VS Code 拡張機能の **Cline** または **Roo Code** の場合：
1. Cline の「MCP Servers」タブを開きます。
2. 「Configure MCP Servers」（`cline_mcp_settings.json`）をクリックします。
3. 以下のブロックを追加します：

```json
{
  "mcpServers": {
    "searxng": {
      "command": "python",
      "args": ["C:/path/to/SearXNGforWindowsNext/tools/mcp_server.py"],
      "env": {
        "SEARXNG_BASE_URL": "http://127.0.0.1:8888"
      },
      "disabled": false,
      "autoApprove": [
        "searxng_search",
        "searxng_scrape",
        "searxng_health"
      ]
    }
  }
}
```

---

### 6. OpenAI Codex CLI / Aider / ターミナル型エージェント

MCP 非対応の環境や、ターミナルコマンド実行能力を持つコーディングエージェント（Aider、Codex CLI、Bash/PowerShell サブエージェントなど）では、**CLI ツール** を直接呼び出すことで同様の検索・本文抽出が可能です。

#### コマンド例

```powershell
# 統合検索 (既定: json_lite 高速スニペット / --mode deep で並列スクレイプ+BM25 / URL入力で自動スクレイプ)
python tools/searxng_cli.py search "Next.js 15 breaking changes" -n 5
python tools/searxng_cli.py search "FastAPI lifespan" --mode deep -d code -n 3
python tools/searxng_cli.py search "https://docs.searxng.org"

# Deep Search 専用サブコマンド
python tools/searxng_cli.py deep "FastAPI lifespan context manager" -n 3

# JSON 形式で結果取得
python tools/searxng_cli.py search "Python 3.12 syntax" --json

# Web ページの本文抽出 (-q で BM25 ハイライト抽出も同時実行)
python tools/searxng_cli.py scrape "https://docs.searxng.org" --max-chars 3000 -q "json_lite"

# バッチラッパーを使用する場合
.\tools\searxng.bat search "FastAPI async SQLAlchemy"
```

#### エージェントへの指示プロンプト例 (`.rules` や `AGENTS.md`)
エージェントに対して SearXNG CLI を利用するよう促す場合、プロジェクトのルールファイルに以下のように記述します：

```markdown
### 外部情報の検索ルール
最新のライブラリ仕様、エラー解決策、公式ドキュメントを調べる必要がある場合は、以下のローカルコマンドを実行して情報を取得してください：
- 深層検索 (推奨): `python tools/searxng_cli.py deep "<検索キーワード/質問>" -n 5` または `python tools/searxng_cli.py search "<検索キーワード/URL>" --mode deep -n 5`
  (※自動で上位サイトを並列スクレイプし、BM25で最も関連するハイライト段落を抽出して返します)
- 高速検索 (`json_lite`): `python tools/searxng_cli.py search "<検索キーワード>" -n 5`
- 個別ページ本文の取得: `python tools/searxng_cli.py scrape "<URL>" --max-chars 3000`
```

---

## 📋 提供ツール仕様

### 1. `searxng_deep_search` (Exa/Tavily スタイル深層検索) ★推奨★

1 回の呼び出しで「メタ検索 → ドメインスコアリング → 並列非同期スクレイプ → BM25ハイライト抽出 → トークン制御」を一貫して実行します。AIエージェントのターン数とトークン消費を最小化しながら最高密度の回答コンテキストを返します。

| パラメータ | 型 | 既定値 | 説明 |
|---|---|---|---|
| `query` | `string` | *(必須)* | 検索キーワード、自然言語の質問、または URL。 |
| `search_depth` | `string` | `"advanced"` | 検索深度。`"advanced"` (並列スクレイプ+BM25ハイライト), `"code"` (公式ドキュメント・GitHub優先), `"basic"` (スニペット+ドメイン評価), `"fast"` (`json_lite` 高速スニペット)。 |
| `max_results` | `integer` | `5` | 取得対象の上位件数 (1〜20件)。 |
| `include_highlights` | `boolean` | `true` | 本文から最もクエリに関連する段落（ハイライト）を抽出するかどうか。 |
| `include_domains` | `array[string]` | `null` | 検索対象を限定するドメインのリスト（例: `["docs.python.org", "github.com"]`）。 |
| `exclude_domains` | `array[string]` | `null` | 除外するドメインのリスト（コピペサイト、不要なドメイン等）。 |
| `max_tokens` | `integer` | `3000` | 生成される Markdown コンテキストの最大トークン予算 (500〜16000)。 |

### 2. `searxng_search` (統合 Web 検索 & URL 自動判別)

既定では SearXNG の高速 `json_lite` 形式で検索を行い、`mode="deep"` や `search_depth` を指定すると統合深層検索を実行します。また `query` に URL（`https://...`）を渡すと自動的に本文抽出を実行します。

| パラメータ | 型 | 既定値 | 説明 |
|---|---|---|---|
| `query` | `string` | *(必須)* | 検索キーワード、質問、または URL (`https://...`)。 |
| `count` | `integer` | `5` | 取得件数 (1〜20件)。コンテキスト効率のため 5件 推奨。 |
| `mode` | `string` | `"auto"` | `"auto"` (URL自動判別 / 既定は高速検索), `"fast"` (`json_lite`), `"deep"` (BM25深層検索), `"scrape"` (URL抽出)。 |
| `search_depth` | `string` | `null` | `"advanced"`, `"code"`, `"basic"`, `"fast"` のいずれかを指定すると統合パイプラインで実行。 |
| `categories` | `string` | `""` | カテゴリ指定（例: `"it"`, `"general"`, `"science"`）。 |
| `engines` | `string` | `""` | 検索エンジン指定（例: `"duckduckgo,bing"`）。 |
| `time_range` | `string` | `""` | 期間指定（`"day"`, `"week"`, `"month"`, `"year"`）。 |
| `include_domains` | `array[string]` | `null` | 検索対象を限定するドメインのリスト。 |
| `exclude_domains` | `array[string]` | `null` | 除外するドメインのリスト。 |
| `max_tokens` | `integer` | `3000` | 深層検索時の最大トークン予算。 |

### 3. `searxng_scrape` (本文抽出 + BM25 ハイライト)

指定された URL の Web ページから本文テキストを抽出し、必要に応じてフォーカスキーワードによる BM25 ハイライト段落も抽出します。

| パラメータ | 型 | 既定値 | 説明 |
|---|---|---|---|
| `url` | `string` | *(必須)* | 抽出対象の Web ページ URL。 |
| `max_length` | `integer` | `4000` | 抽出文字数の上限（コンテキスト溢れ防止）。 |
| `query` | `string` | `""` | 任意。指定するとページ本文からクエリに関連する BM25 ハイライト段落を抽出。 |

### 4. `searxng_health` (ヘルスチェック)

SearXNG サーバーの稼働状態を確認します。引数はありません。

---

## 🔧 トラブルシューティング & FAQ

### Q1. エージェントが「SearXNG サーバーに接続できませんでした」と出力する
- **原因**: SearXNG サーバーがバックグラウンドまたは別ウィンドウで起動していません。
- **対処**: プロジェクトディレクトリ内の `SearXNG for Windows.bat` を起動してください。ポート 8888 で待機状態になれば解消します。

### Q2. サーバーのポート番号を変更している場合
- `SearXNG for Windows.bat` または環境変数 `SEARXNG_PORT` で別のポート（例: 9000）を使用している場合、エージェント設定の `env` または環境変数 `SEARXNG_BASE_URL` に `http://127.0.0.1:9000` を設定してください。

### Q3. スクレイピング時に「安全機構 (SSRF対策) によりブロックされました」となる
- **仕様**: `localhost`、`127.0.0.1`、`192.168.x.x`、`10.x.x.x`、`file://` スキームなどのプライベート/ローカルアドレスへのリクエストは、安全のため遮断（HTTP 400）されます。外部の正規 URL を指定してください。
