<p align="center">
  <img src="images/logo.png" alt="SearXNG Next Logo" width="300">
</p>



# SearXNG for Windows Next 🚀

**GenAIフレンドリーな検索体験を、Windowsネイティブ環境で。**

このプロジェクトは、Windows環境でSearXNGを最適に動作させつつ、LLM（大規模言語モデル）やAPIワークフローから利用しやすい**軽量・高速な検索結果取得**を実現することを目的としたフォークリポジトリです。

---

##  主な特徴

-  Windows Native: 組み込みPython環境により、DockerなしでWindows上で直接動作。
-  GenAI Optimized: LLMのトークン消費を抑える専用の `json_lite` フォーマットを搭載。
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
`SearXNG for Windows.bat` を実行します。起動後、ブラウザで [http://127.0.0.1:8888](http://127.0.0.1:8888) にアクセスできれば成功です。

### 3. 動作確認 (Testing)
以下のコマンドを実行して、特に `json_lite` 形式のレスポンスが正しく返ってくるか確認できます。

**PowerShell:**
```powershell
Invoke-RestMethod "http://127.0.0.1:8888/search?q=SearXNG&format=json_lite" | ConvertTo-Json -Depth 5
```

**curl:**
```bash
curl -G "http://127.0.0.1:8888/search" --data-urlencode "q=SearXNG" --data-urlencode "format=json_lite"
```

---

##  GenAI / LLM での活用例

このプロジェクトの最大の特徴は、AIエージェント向けの**超軽量JSONレスポンス**です。

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
        url = f"http://localhost:8888/search?q={query}&format=json_lite"
        try:
            response = requests.get(url, timeout=10)
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
        scrape_api_url = f"http://localhost:8888/scrape?url={url}"
        try:
            response = requests.get(scrape_api_url, timeout=15)
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

## 🔒 過去の漏えい secret_key の履歴パージ（任意・破壊的操作）

git の履歴には、本機能追加より前のローテーションでコミットされた実 secret_key 値が複数含まれています（`654eba279a…`, `4d7e7376…`, `c131e23e…`, `7daba020…`, `cbe7de3a…`, `190c2fa5…`, `5634bc6d…`, `abd85945…` など）。**これらは既にリポジトリを clone できる全員に見えており**、本変更は将来のコミットに実 key が入らないようにするものに過ぎません。過去の履歴を完全に消すには **force-push を伴う破壊的な履歴書き換え**が必要で、協調的な作業が要求されます。

実施する場合の手順（管理者向け）:

```bash
# 1. メンテナのフレッシュな clone で実行する（filter-repo は fresh clone を要求する）
git clone <this-repo> searxng-purge
cd searxng-purge
git fetch --tags --unshallow   # 必要なら

# 2. 置換ファイル（scratch/replacements.txt と同じ内容）
cat > /tmp/replacements.txt <<'EOF'
9f2e5f8b6f1c4a8da1e4e9d5f0b2c7a49b1f9e2d3c4a5b6d7e8f9a0b1c2d3e4==>REDACTED-LEAKED-SECRET-KEY
654eba279ae3354410f8c36f11535af7b1d6f893482cccad86268bdd50a047c1==>REDACTED-LEAKED-SECRET-KEY
4d7e7376e13c5de05bd915d4e270928abf72686db55a58b27ae3d5c14cf387d4==>REDACTED-LEAKED-SECRET-KEY
c131e23ee31e69e1f16c712e6e1b3e1a7b20b976bf75f10d2a45da807201ba70==>REDACTED-LEAKED-SECRET-KEY
7daba0202efb9448f5bcd68e7e4897d046346b1cdcf2804a72cd60039944442e==>REDACTED-LEAKED-SECRET-KEY
5634bc6dbe3b4ea589c6895333e911a15e1e089031ba6080008fdc5b548fae95==>REDACTED-LEAKED-SECRET-KEY
190c2fa54e6ae2ab4fea0f2eb21365321b658f3029f1fb40de754a40d9f5da62==>REDACTED-LEAKED-SECRET-KEY
cbe7de3a7f6a7572353f0e492466d739c517ce6d516c369bd893605cae8da17b==>REDACTED-LEAKED-SECRET-KEY
abd85945bf0253faba5a3594c83236bdf73270d838ffa1e5a3a174d665fccb4d==>REDACTED-LEAKED-SECRET-KEY
EOF

# 3. 履歴を書き換える
git-filter-repo --force --replace-text /tmp/replacements.txt

# 4. 検証: 上記の key 値がコミット中に残っていないこと
git log -p -- config/settings.yml | grep -E "secret_key:" | grep -vE "REDACTED|ultrasecretkey|CHANGE_ME" || echo "OK: no leaked keys in history"

# 5. 強制 push（リポジトリの全 clone に対して周知が必要）
git remote add origin <this-repo>
git push --force --tags --all
```

> ⚠️ force-push 後は、旧 SHA を保持している全 clone が `main` の upstream から分岐した状態になります。共同作業者は `git fetch origin && git reset --hard origin/main` で再同期する必要があります。
