<p align="center">
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
検索結果のスニペットだけでは情報が不足する場合、AIが特定のURLを指定してそのページの**本文のみ**を抽出して取得できます。精度向上のため `trafilatura` ライブラリを使用しています。

**リクエスト例:**
```http
GET http://127.0.0.1:8888/scrape?url=https://example.com/article
```

**レスポンス例:**
```json
{
  "url": "https://example.com/article",
  "content": "ここに抽出された本文が表示されます...",
}
```



### Open WebUI での活用例 (Tool として登録)

Open WebUI を使用している場合、この SearXNG フォークの「検索（json_lite）」および「スクレイピング（scrape）」機能をツールとして登録することで、AI が必要に応じて Web 検索と本文抽出を組み合わせて実行できるようになります。なおこの機能に関してが未テストであり、想定していた動作結果が得られない可能性があります。

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
            return response.text
        except Exception as e:
            return f"SearXNG への接続エラー: {str(e)}"

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
            # 抽出された本文のみを返す
            return response.json().get("content", "本文の抽出に失敗しました。")
        except Exception as e:
            return f"スクレイピングエラー: {str(e)}"
```

#### 2. モデルへの適用
作成したツールを保存した後、チャット画面のモデル設定（または「Workspace」→「Models」）から、このツールを有効にします。これで、AI が「検索が必要だ」と判断した際に、トークン効率の極めて高い `json_lite` 形式で情報を取得できるようになります。

---

##  構成ファイル

- **`SearXNG for Windows.bat`**: メインの起動スクリプト。
- **`config/settings.yml`**: ユーザー設定（エンジン、ポート、フォーマットなど）。
- **`tools/sync-upstream.ps1`**: 本家リポジトリとの同期およびパッチ適用。
- **`python/`**: ポータブルな組み込みPython環境。

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
