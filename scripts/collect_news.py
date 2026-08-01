import os
import json
import urllib.request
import urllib.parse
import datetime
import xml.etree.ElementTree as ET
import re

def clean_html(raw_html):
    """HTMLタグや特殊文字を完全に除去してテキストだけにする"""
    if not raw_html:
        return ""
    # HTMLタグを除去
    cleanr = re.compile('<.*?>')
    cleandText = re.sub(cleanr, '', raw_html)
    # &nbsp; などの特殊文字を除去
    cleandText = cleandText.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return cleandText.strip()

def get_gemini_summary(raw_news, api_key):
    print("-> Gemini APIによるニュースの自動検索・内容自動要約を実行中...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    prompt = f"""以下のニュース内容をしっかりと読み込み、URLやHTMLタグは一切含めず、受験生向けに分かりやすくまとめた要約記事を作成してください。
余計なHTMLやリンク文字列はすべて排除し、純粋な日本語の文章だけで要約してください。
必ず以下のJSONフォーマットのみで出力してください。他の文字やMarkdownの記号（jsonという文字など）は含めないでください。

{{"title": "30文字程度の見出し", "content": "300〜500文字の要約本文", "isBreaking": false}}

【収集したニュース内容】
{raw_news}"""

    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {
            "parts": [{"text": "あなたは大学入試専門の新聞編集長です。提供されたニュースからHTMLタグやURLを完全に取り除き、内容を分かりやすく要約して新聞記事を作成してください。本当に重大な変更や緊急ニュースの場合のみisBreakingをtrueにしてください。"}]
        },
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    req = urllib.request.Request(
        url, 
        data=json.dumps(data).encode('utf-8'), 
        headers={'Content-Type': 'application/json'}, 
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            res_body = response.read().decode('utf-8')
            res_json = json.loads(res_body)
            if 'candidates' in res_json and len(res_json['candidates']) > 0:
                text = res_json['candidates'][0]['content']['parts'][0]['text']
                print("-> Geminiによる自動要約に成功しました。")
                return text
    except Exception as e:
        print(f"【エラー】Gemini API要約失敗: {e}")
    return None

def fetch_news():
    print("-> Googleニュースの自動検索中...")
    query = urllib.parse.quote("共通テスト 大学入試 変更 速報")
    url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            root = ET.fromstring(response.read())
            texts = []
            for item in root.findall(".//item")[:10]:
                title = item.find("title").text if item.find("title") is not None else ""
                desc = item.find("description").text if item.find("description") is not None else ""
                
                # HTMLタグやURLを完全に綺麗に除去
                clean_title = clean_html(title)
                clean_desc = clean_html(desc)
                # 残ったhttpリンク文字列の削除
                clean_desc = re.sub(r'http\S+', '', clean_desc)
                
                if clean_title or clean_desc:
                    texts.append(f"・{clean_title}: {clean_desc}")
                    
            print(f"-> 検索ヒット数: {len(texts)}件")
            return "\n".join(texts)
    except Exception as e:
        print(f"【エラー】ニュース自動検索失敗: {e}")
        return ""

def check_existing_articles(project_id, app_id, today_str):
    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/artifacts/{app_id}/public/data/articles"
    req = urllib.request.Request(url, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            documents = res_json.get('documents', [])
            
            count = len(documents)
            has_today_regular = False
            for doc in documents:
                fields = doc.get("fields", {})
                is_breaking = fields.get("isBreaking", {}).get("booleanValue", False)
                pub_date = fields.get("publishDate", {}).get("stringValue", "")
                content_text = fields.get("content", {}).get("stringValue", "")
                
                if today_str in pub_date and not is_breaking:
                    if "要約記事を取得中です" not in content_text and "ニュースを取得中です" not in content_text:
                        has_today_regular = True
                        break
                    
            return count, has_today_regular
    except Exception as e:
        print(f"既存記事の取得スキップ: {e}")
        return 0, False

def main():
    print("=== 入試ニュース自動検索・要約プログラム（HTMLタグ除去版）開始 ===")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("【エラー】GEMINI_API_KEY が設定されていません。")
        return

    project_id = "nyushi-nippo"
    app_id = os.environ.get("APP_ID", "nyushi-nippo-app")
    
    now_jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    today_str = now_jst.strftime("%Y年%m月%d日")

    existing_count, has_today_regular = check_existing_articles(project_id, app_id, today_str)
    is_first_issue = (existing_count == 0)
    
    # 1. Googleニュースから最新情報を自動検索
    raw_news = fetch_news()
    
    if not raw_news and is_first_issue:
        article_data = {
            "title": "入試日報新聞 創刊の辞：受験生を支える確かな情報へ",
            "content": "本日ここに、大学入試および共通テストの最新動向を自動集約してお伝えする「入試日報新聞」の創刊号を発刊いたします。本紙は毎週火曜・木曜・土曜・日曜の週4回、最新の入試情報を分かりやすく要約して皆様にお届けします。また、重大な変更や速報が入った場合には随時お届けいたします。",
            "isBreaking": False
        }
    else:
        fallback_content = "【入試最新動向まとめ】\n\n" + raw_news[:450] if raw_news else "現在新しい入試関連のニュースはありません。"
        article_data = {"title": "最新の入試動向と対策まとめ", "content": fallback_content, "isBreaking": False}
        
        # 2. 取ってきたニュースをGeminiで自動要約
        if raw_news:
            gemini_text = get_gemini_summary(raw_news, api_key)
            if gemini_text:
                try:
                    cleaned = gemini_text.strip()
                    if cleaned.startswith("```"):
                        cleaned = cleaned.split("\n", 1)[-1]
                    if cleaned.endswith("```"):
                        cleaned = cleaned.rsplit("\n", 1)[0]
                    article_data = json.loads(cleaned)
                    print("-> 自動要約データの解析に成功しました。")
                except Exception as e:
                    print(f"【警告】JSONパース失敗のためテキストを整形して使用します: {e}")
                    article_data["content"] = clean_html(gemini_text[:450])

    if not article_data.get("isBreaking", False) and has_today_regular:
        print("✓ 本日の定例号はすでに発行済みです。スキップします。")
        return

    issue_label = "（創刊号）" if is_first_issue else f"（第{existing_count + 1}号）"
    publish_date_str = today_str + f" {issue_label}"

    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/artifacts/{app_id}/public/data/articles"
    
    payload = {
        "fields": {
            "title": {"stringValue": article_data.get("title", "無題")},
            "content": {"stringValue": clean_html(article_data.get("content", ""))},
            "isBreaking": {"booleanValue": bool(article_data.get("isBreaking", False))},
            "publishDate": {"stringValue": publish_date_str},
            "createdAt": {"timestampValue": now_jst.isoformat("T")}
        }
    }
    
    req = urllib.request.Request(
        url, 
        data=json.dumps(payload).encode('utf-8'), 
        headers={'Content-Type': 'application/json'}, 
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status == 200:
                print("✓ 【成功】HTMLタグを除去した綺麗な記事のFirestore保存が完了しました！")
    except Exception as e:
        print(f"【エラー】Firestore保存失敗: {e}")

if __name__ == "__main__":
    main()

