import os
import asyncio
import json
import time
from typing import List, Dict
from playwright.async_api import async_playwright
from google import genai
from google.genai import types
from dotenv import load_dotenv
from PIL import Image
import io

# Load environment variables
load_dotenv()

async def scroll_to_bottom(page):
    """Scrolls to the bottom of the page to trigger lazy loading."""
    await page.evaluate("""
        async () => {
            await new Promise((resolve) => {
                let totalHeight = 0;
                let distance = 300;
                let timer = setInterval(() => {
                    let scrollHeight = document.body.scrollHeight;
                    window.scrollBy(0, distance);
                    totalHeight += distance;
                    if(totalHeight >= scrollHeight){
                        clearInterval(timer);
                        resolve();
                    }
                }, 100);
            });
        }
    """)

async def analyze_lp(url: str, api_key: str = None, model_name: str = "gemini-2.0-flash"):
    print(f"Analyzing: {url} using {model_name}")
    
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        print("Error: API Key is required.")
        return {"error": "API Key is required."}

    # Initialize New SDK Client
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        return {"error": f"SDKクライアントの初期化に失敗しました: {str(e)}"}
    
    async with async_playwright() as p:
        # Check env var
        remote_url = os.environ.get("REMOTE_BROWSER_URL")
        
        # Debug: Print all env keys to Vercel logs (safe)
        print(f"DEBUG: Available environment keys: {list(os.environ.keys())}")
        
        if remote_url:
            print(f"Connecting to remote browser: {remote_url[:15]}...")
            try:
                browser = await p.chromium.connect_over_cdp(remote_url)
            except Exception as e:
                print(f"Remote connection failed: {e}")
                return {"error": f"リモートブラウザに接続できませんでした。URLまたはトークンを確認してください。: {str(e)}"}
        else:
            # Check if we are on Vercel (usually has VERCEL=1)
            is_vercel = os.environ.get("VERCEL") == "1"
            if is_vercel:
                print("ERROR: REMOTE_BROWSER_URL is missing on Vercel!")
                return {"error": "環境変数 'REMOTE_BROWSER_URL' が設定されていません。Vercelの管理画面で設定し、デプロイし直してください。"}
            
            print("Launching local browser (Development mode)...")
            browser = await p.chromium.launch(headless=True)
            
        context = await browser.new_context(
            viewport={"width": 375, "height": 812},
            device_scale_factor=2
        )
        page = await context.new_page()
        
        try:
            # Set a long timeout and wait for network idle
            await page.goto(url, wait_until="networkidle", timeout=90000)
            
            # Scroll to trigger lazy loading
            print("Scrolling to load content...")
            await scroll_to_bottom(page)
            
            # Additional wait for images to actually decode/render
            await asyncio.sleep(2)
            
            # Scroll back to top if needed for some reason, though full_page=True handles it
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(1)
            
        except Exception as e:
            print(f"Failed to load page: {e}")
            await browser.close()
            return {"error": f"Failed to load page: {str(e)}"}
        
        # Take full page screenshot
        screenshot_path = "lp_screenshot.png"
        await page.screenshot(path=screenshot_path, full_page=True, type="png")
        
        # Image Compression Logic (Keeping it but increasing quality)
        compressed_path = "lp_screenshot_min.jpg"
        try:
            with Image.open(screenshot_path) as img:
                # Convert to RGB
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                
                # Resize if EXTREMELY long, but keep it high enough for text readability
                max_height = 8000 
                if img.height > max_height:
                    new_width = int(img.width * (max_height / img.height))
                    img = img.resize((new_width, max_height), Image.LANCZOS)
                
                # Save as JPEG with higher quality (85%)
                img.save(compressed_path, "JPEG", quality=85, optimize=True)
                print(f"Image optimized: {screenshot_path} -> {compressed_path}")
        except Exception as e:
            print(f"Optimization failed: {e}")
            compressed_path = screenshot_path

        # Extract text content
        text_content = await page.evaluate("() => document.body.innerText")
        
        await browser.close()
        
        # Prepare AI analysis
        frameworks_desc = """
        - PASONA: Problem -> Agitation -> Solution -> Narrow Down -> Action
        - BEAF: Benefit -> Evidence -> Advantage -> Feature
        - AIDCAS: Attention -> Interest -> Desire -> Conviction -> Action -> Satisfaction
        - QUEST: Qualify -> Understand -> Educate -> Simulate -> Transition
        """
        
        prompt = f"""
        あなたはプロのLPディレクターです。提供されたLPのスクリーンショットとテキストを分析し、詳細な分析レポート（LP分析2号）を構成案として生成してください。
        
        【分析対象URL】: {url}
        【抽出テキスト（先頭部分）】: {text_content[:2000]}
        
        【出力形式】: JSON
        
        【重要】: 
        出力は必ず以下のキーを持つJSON形式にしてください。日本語で詳しく分析してください。
        「チェックリスト評価」には、必ず以下の7項目すべてを含めてください：
        1. FV要件 (キャッチコピー、権威性、ベネフィット、CTAがFVに含まれているか)
        2. 広告との整合性 (訴求内容が一致しているか)
        3. 価値提案 (独自の強みやベネフィットが明確か)
        4. 信頼性・証拠 (実績、口コミ、エビデンスの質)
        5. CTAの設計 (ボタン配置、マイクロコピー、オファー内容)
        6. 可読性・操作性 (文字サイズ、余白、ページ速度、ナビゲーション)
        7. モバイル最適化 (SP表示での使いやすさ、フォントサイズ)

        {{
          "チェックリスト評価": [
            {{"項目": "FV要件", "評価": 5, "根拠": "..."}},
            {{"項目": "広告との整合性", "評価": 5, "根拠": "..."}},
            {{"項目": "価値提案", "評価": 5, "根拠": "..."}},
            {{"項目": "信頼性・証拠", "評価": 5, "根拠": "..."}},
            {{"項目": "CTAの設計", "評価": 5, "根拠": "..."}},
            {{"項目": "可読性・操作性", "評価": 5, "根拠": "..."}},
            {{"項目": "モバイル最適化", "評価": 5, "根拠": "..."}}
          ],
          "フレームワーク": "PASONA、BEAF、AIDCAS、QUESTのいずれか最適なもの",
          "フレームワーク解説": "どのように適用されているか、ストーリーの繋がり",
          "構成": [
            {{"title": "セクション名", "description": "内容や狙いの解説"}},
            ...
          ],
          "改善課題": ["具体的な改善提案1", "具体的な改善提案2", "..."],
          "競合他社": [
            {{"社名": "...", "URL": "..."}},
            ...
          ]
        }}
        """
        
        # Prepare Media Part
        with open(compressed_path, "rb") as f:
            image_data = f.read()
            image_part = types.Part.from_bytes(data=image_data, mime_type="image/jpeg" if compressed_path.endswith(".jpg") else "image/png")
        
        try:
            # Generate content
            response = client.models.generate_content(
                model=model_name,
                contents=[prompt, image_part],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            
            report_text = response.text
            
            # Robust JSON extraction
            json_start = report_text.find('{')
            json_end = report_text.rfind('}')
            if json_start != -1 and json_end != -1:
                report_text = report_text[json_start:json_end+1]
            
            report_data = json.loads(report_text)
            return report_data
        except Exception as e:
            print(f"Failed analysis: {e}")
            error_str = str(e)
            if "429" in error_str or "quota" in error_str.lower():
                return {"error": "APIクォータ制限を超えました。", "details": error_str, "status": "QUOTA_EXCEEDED"}
            return {"error": f"AI分析中にエラーが発生しました: {error_str}"}

if __name__ == "__main__":
    import asyncio
    asyncio.run(analyze_lp("https://example.com"))
