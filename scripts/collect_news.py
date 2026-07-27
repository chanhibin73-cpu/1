name: Auto Exam News Collector

on:
  schedule:
    - cron: '1 3 * * 0,3'
    - cron: '0 * * * *'
  workflow_dispatch:

jobs:
  collect-and-update:
    runs-on: ubuntu-latest

    steps:
      - name: リポジトリのチェックアウト
        uses: actions/checkout@v4

      - name: Python環境のセットアップ
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: 依存ライブラリのインストール
        run: |
          python -m pip install --upgrade pip
          pip install google-generativeai requests

      - name: ニュース収集＆Gemini要約・Firestore保存の実行
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          APP_ID: ${{ secrets.APP_ID }}
        run: |
          python -c '
          import os
          import json
          import re
          import requests
          import datetime
          import urllib.parse
          import google.generativeai as genai

          print("=== プログラムの実行を開始します ===")
          GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
          if not GEMINI_API_KEY:
              print("【エラー】GEMINI_API_KEY が設定されていません。")
              exit(1)

          genai.configure(api_key=GEMINI_API_KEY)

          # 1. RSSニュース取得
          query = urllib.parse.quote("共通テスト 大学入試 情報")
          rss_url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
          
          response = requests.get(rss_url, timeout=10)
          if response.status_code != 200:
              print("ニュースの取得に失敗しました。")
              exit(1)

          from xml.etree import ElementTree as ET
          root = ET.fromstring(response.content)
          articles_text = []
          for item in root.findall(".//item")[:8]:
              title = item.find("title").text if item.find("title") is not None else ""
              description = item.find("description").text if item.find("description") is not None else ""
              articles_text.append(f"・{title}: {description}")
          raw_news = "\n".join(articles_text)

          # 2. Gemini要約
          system_instruction = "あなたは大学入試専門の新聞編集長です。与えたニュースから新聞記事用の「タイトル」と「本文」を生成してください。"
          prompt = f"以下のニュースから新聞記事を作成し、必ず以下のJSONフォーマットのみで出力してください。\n{{\"title\": \"30文字程度の見出し\", \"content\": \"300〜500文字の要約本文\", \"isBreaking\": false}}\n\n【ニュース】\n{raw_news}"

          model = genai.GenerativeModel(model_name="gemini-3.6-flash", system_instruction=system_instruction)
          res = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
          raw_text = res.text.strip()
    cleaned_text = re.sub(r'\s*```$', '', cleaned_text, flags=re.MULTILINE).strip()
    
    return json.loads(cleaned_text)

# --- 4. Firestoreへの保存 (REST API方式：秘密鍵エラーを完全回避) ---
def save_to_firestore(article_data):
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    date_str = now.strftime("%Y年%m月%d日")
    
    # プロジェクトIDとアプリIDを直接指定
    project_id = "nyushi-nippo"
    app_id = os.environ.get("APP_ID", "nyushi-nippo-app")
    
    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/artifacts/{app_id}/public/data/articles"
    
    # REST API用のデータフォーマット
    payload = {
        "fields": {
            "title": {"stringValue": article_data.get("title", "無題")},
            "content": {"stringValue": article_data.get("content", "")},
            "isBreaking": {"booleanValue": bool(article_data.get("isBreaking", False))},
            "publishDate": {"stringValue": date_str},
            "createdAt": {"timestampValue": now.isoformat('T')} # タイムスタンプ
        }
    }
    
    try:
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            doc_id = response.json().get("name", "").split("/")[-1]
            print(f"✓ 記事をFirestoreに正常保存しました: 文書ID [{doc_id}]")
        else:
            print(f"【エラー】Firestoreへの保存に失敗。ステータス: {response.status_code}")
            print(f"詳細: {response.text}")
    except Exception as e:
        print(f"【通信エラー】Firestore保存中にエラー発生: {e}")

def main():
    print("1. 最新入試ニュースの収集を開始...")
    raw_news = fetch_latest_exam_news()
    
    if not raw_news:
        print("有効なニュースが見つかりませんでした。")
        return
        
    print("2. Geminiによる要約と新聞記事作成...")
    article = generate_newspaper_article(raw_news)
    print(f"★生成された新聞タイトル: 【{article.get('title')}】")
    
    print("3. Firestoreへ書き込み中...")
    save_to_firestore(article)
    print("=== 全処理が正常に完了しました ===")

if __name__ == "__main__":
    main()


