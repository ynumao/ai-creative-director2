import os
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import asyncio
from analyze_lp import analyze_lp
import json

app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.json
    url = data.get('url')
    api_key = data.get('api_key')
    selected_model = data.get('model', 'gemini-2.0-flash')
    
    # Fallback sequence
    models_to_try = [selected_model]
    defaults = ['gemini-2.0-flash', 'gemini-flash-latest', 'gemini-pro-latest']
    for d in defaults:
        if d not in models_to_try:
            models_to_try.append(d)

    if not url:
        return jsonify({"error": "URL is required"}), 400
    
    # Run the async analysis
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        last_error = None
        for i, model_name in enumerate(models_to_try):
            print(f"Attempting analysis with {model_name} (Attempt {i+1})")
            report = loop.run_until_complete(analyze_lp(url, api_key, model_name))
            
            if report and "error" not in report:
                # Success!
                report["used_model"] = model_name
                report["is_fallback"] = (i > 0)
                return jsonify(report)
            
            # If it's a quota error, try next model
            if report and report.get("status") == "QUOTA_EXCEEDED":
                print(f"Quota exceeded for {model_name}. Trying fallback...")
                last_error = report
                continue
            else:
                # Other errors (404, etc.) - return immediately
                return jsonify(report or {"error": "Unknown error"}), 400
        
        # If we exhausted all models
        return jsonify(last_error or {"error": "All models exhausted"}), 429

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        loop.close()

@app.route('/screenshot')
def screenshot():
    if os.path.exists('lp_screenshot_min.jpg'):
        return send_from_directory('.', 'lp_screenshot_min.jpg')
    return send_from_directory('.', 'lp_screenshot.png')

if __name__ == '__main__':
    app.run(debug=True, port=5001)
