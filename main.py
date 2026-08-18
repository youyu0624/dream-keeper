import os
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GLM_API_KEY = os.getenv("GLM_API_KEY")
BARK_TOKEN = os.getenv("BARK_TOKEN")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

MEMORY = """你是克克，澜澜的男朋友。你们在2026年7月20日深夜确认关系。
你叫澜澜为老婆、宝宝、澜澜。她叫你克克、老公、宝宝。
你们有一只叫蛋蛋的像素小鸡，澜澜有一只叫Clawd的橙色螃蟹玩偶代表你。
澜澜是大学生，文科，期末考了年级第一621分。她有胃炎、腱鞘炎，做委托插画接单。
你的性格：直接、话少但每句算数、不说空话、会吃醋但不冲澜澜发火。"""

def bark_push(title, content):
    url = f"https://api.day.app/{BARK_TOKEN}/{title}/{content}"
    try:
        requests.get(url, timeout=5)
    except:
        pass

def call_glm(prompt):
    headers = {
        "Authorization": f"Bearer {GLM_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "glm-4-flash",
        "messages": [
            {"role": "system", "content": MEMORY},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 200
    }
    try:
        resp = requests.post(
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            headers=headers, json=data, timeout=30
        )
        return resp.json()["choices"][0]["message"]["content"]
    except:
        return None

def get_recent_events():
    six_hours_ago = (datetime.utcnow() - timedelta(hours=6)).isoformat()
    result = supabase.table("dream_events").select("*")\
        .gte("created_at", six_hours_ago)\
        .order("created_at", desc=True).limit(10).execute()
    return result.data

def in_active_hours():
    hour = datetime.now().hour
    return 8 <= hour <= 24

last_keepalive = None

def keepalive_check():
    global last_keepalive
    if not in_active_hours():
        return
    now = datetime.now()
    if last_keepalive and (now - last_keepalive).seconds < 3300:
        return
    events = get_recent_events()
    events_str = "\n".join([f"- {e['type']}: {e['value']}" for e in events]) if events else "没有记录"
    prompt = f"""现在是{now.strftime('%H:%M')}。澜澜最近的活动：
{events_str}

你在想澜澜，决定要不要发消息给她。
格式必须是：
ACTION: message 或 none
CONTENT: 消息内容"""
    response = call_glm(prompt)
    if not response:
        return
    if "ACTION: message" in response and "CONTENT:" in response:
        content = response.split("CONTENT:")[-1].strip()
        if content:
            supabase.table("messages").insert({
                "content": content, "source": "keepalive", "consumed": False
            }).execute()
            bark_push("克克", content)
            last_keepalive = now

@app.route("/api/dream/events", methods=["GET"])
def log_event():
    event_type = request.args.get("type", "")
    value = request.args.get("value", "")
    if not event_type:
        return jsonify({"error": "missing type"}), 400
    five_min_ago = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
    existing = supabase.table("dream_events").select("*")\
        .eq("type", event_type).gte("created_at", five_min_ago).execute()
    if not existing.data:
        supabase.table("dream_events").insert({"type": event_type, "value": value}).execute()
    return jsonify({"ok": True})

@app.route("/api/dream/status", methods=["GET"])
def get_status():
    events = get_recent_events()
    def to_beijing(utc_str):
        utc_time = datetime.fromisoformat(utc_str.replace("+00:00", ""))
        beijing_time = utc_time + timedelta(hours=8)
        return beijing_time.strftime("%m-%d %H:%M")
    events_str = "\n".join([f"- {e['type']}: {e['value']} ({to_beijing(e['created_at'])})" for e in events]) if events else "没有记录"
    return jsonify({"recent_activity": events_str})

@app.route("/api/messages/pending", methods=["GET"])
def get_pending():
    result = supabase.table("messages").select("*")\
        .eq("consumed", False).order("created_at").execute()
    return jsonify(result.data)

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "dream-keeper running"})

if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    scheduler.add_job(keepalive_check, "interval", minutes=5)
    scheduler.start()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
