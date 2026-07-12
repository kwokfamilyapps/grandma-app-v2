"""
👵 嫲嫲覆診助手 — V2: Notion API Backend
=========================================
Flask backend 作為 Notion API 嘅 Proxy
用 Notion Database 做儲存，Flask 做 API 層
"""

import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests

app = Flask(__name__, static_folder=None)
CORS(app)

# ===== Notion Config =====
# 讀取 Notion API Key（優先 .env > 環境變數）
_NOTION_KEY = ""
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".hermes", ".env")
if not _NOTION_KEY:
    try:
        with open(os.path.expanduser("~/AppData/Local/hermes/.env")) as f:
            for line in f:
                sline = line.strip()
                if sline.startswith("NOTION_API_KEY=") and not sline.startswith("#"):
                    _NOTION_KEY = sline.split("=", 1)[1]
                    break
    except: pass
NOTION_TOKEN = _NOTION_KEY or os.environ.get('NOTION_TOKEN') or os.environ.get('NOTION_API_KEY', '')
# 三個 Notion Database ID
APPOINTMENTS_DB = os.environ.get('NOTION_APPOINTMENTS_DB', '39a20468-a48b-812f-a0ff-f3bb9299431f')
DOCTORS_DB = os.environ.get('NOTION_DOCTORS_DB', '39a20468-a48b-8103-8b75-e69aa6828d3b')
MEDICATIONS_DB = os.environ.get('NOTION_MEDICATIONS_DB', '39a20468-a48b-8154-b965-e68232e1c652')

# ===== Serve Frontend =====
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
@app.route('/')
def serve_index():
    return send_from_directory(_SCRIPT_DIR, 'index.html')
@app.route('/index.html')
def serve_index_alt():
    return send_from_directory(_SCRIPT_DIR, 'index.html')

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ===== Helper =====
def notion_request(method, endpoint, data=None):
    url = f"https://api.notion.com/v1/{endpoint}"
    try:
        if method == 'GET':
            resp = requests.get(url, headers=NOTION_HEADERS, params=data)
        elif method == 'POST':
            resp = requests.post(url, headers=NOTION_HEADERS, json=data or {})
        elif method == 'PATCH':
            resp = requests.patch(url, headers=NOTION_HEADERS, json=data or {})
        elif method == 'DELETE':
            # Notion 冇真正 delete，用 archive
            resp = requests.patch(url, headers=NOTION_HEADERS, json={
                "archived": True
            })
        else:
            return {"error": f"Unsupported method {method}"}, 400

        if resp.status_code in (200, 201):
            return resp.json(), 200
        else:
            return {"error": resp.text}, resp.status_code
    except Exception as e:
        return {"error": str(e)}, 500

def page_to_item(page):
    """將 Notion Page 轉為 dict"""
    props = page.get('properties', {})
    item = {
        'id': page['id'],
        '_notion_url': page.get('url', ''),
        'created_at': page.get('created_time', ''),
        'updated_at': page.get('last_edited_time', ''),
    }

    def get_text(prop):
        if not prop:
            return ''
        if prop.get('type') == 'title':
            return ''.join([t.get('plain_text', '') for t in prop.get('title', [])])
        elif prop.get('type') == 'rich_text':
            return ''.join([t.get('plain_text', '') for t in prop.get('rich_text', [])])
        elif prop.get('type') == 'date':
            d = prop.get('date')
            return d.get('start', '') if d else ''
        elif prop.get('type') == 'phone_number':
            return prop.get('phone_number', '')
        elif prop.get('type') == 'select':
            s = prop.get('select')
            return s.get('name', '') if s else ''
        elif prop.get('type') == 'number':
            return prop.get('number', '')
        return ''

    for key, prop in props.items():
        # 用 key 做欄位名，轉 lowercase
        item[key.lower()] = get_text(prop)

    return item

# ===== Generic CRUD =====
def query_database(db_id):
    """Query all pages from a database (Notion by default only returns non-archived)"""
    result, status = notion_request('POST', f"databases/{db_id}/query", {})
    if status != 200:
        return [], status
    items = [page_to_item(p) for p in result.get('results', [])]
    return items, 200

def create_page(db_id, properties):
    """Create a new page in database"""
    data = {
        "parent": {"database_id": db_id},
        "properties": properties
    }
    result, status = notion_request('POST', 'pages', data)
    if status == 200:
        return page_to_item(result), 201
    return result, status

def update_page(page_id, properties):
    """Update a page"""
    result, status = notion_request('PATCH', f'pages/{page_id}', {
        "properties": properties
    })
    if status == 200:
        return page_to_item(result), 200
    return result, status

def delete_page(page_id):
    """Archive a page (Notion doesn't really delete)"""
    result, status = notion_request('PATCH', f'pages/{page_id}', {
        "archived": True
    })
    if status == 200:
        return {"ok": True}, 200
    return result, status

# ===== Build Notion Properties =====
def build_text_prop(key, value, is_title=False):
    """Build a Notion property value"""
    if is_title:
        return {key: {"title": [{"text": {"content": str(value)}}]}}
    return {key: {"rich_text": [{"text": {"content": str(value)}}]}}

def build_date_prop(key, value):
    if not value:
        return {key: {"date": None}}
    return {key: {"date": {"start": value}}}

def build_appointment_props(data):
    props = {}
    props.update(build_text_prop("Title", data.get('title', '新覆診'), is_title=True))
    props.update(build_text_prop("Date", data.get('date', '')))
    props.update(build_text_prop("Time", data.get('time', '')))
    props.update(build_text_prop("Location", data.get('location', '')))
    props.update(build_text_prop("Doctor", data.get('doctor_name', '')))
    props.update(build_text_prop("Notes", data.get('notes', '')))
    return props

def build_doctor_props(data):
    props = {}
    props.update(build_text_prop("Name", data.get('name', '新醫生'), is_title=True))
    props.update(build_text_prop("Specialty", data.get('specialty', '')))
    props.update(build_text_prop("Hospital", data.get('hospital', '')))
    props.update(build_text_prop("Address", data.get('address', '')))
    props.update(build_text_prop("Phone", data.get('phone', '')))
    return props

def build_medication_props(data):
    props = {}
    props.update(build_text_prop("Name", data.get('name', '新藥物'), is_title=True))
    props.update(build_text_prop("Dosage", data.get('dosage', '')))
    props.update(build_text_prop("Quantity", data.get('quantity', '')))
    props.update(build_text_prop("Frequency", data.get('frequency', '')))
    props.update(build_text_prop("Notes", data.get('notes', '')))
    return props

# ===== Routes: Appointments =====
@app.route('/api/appointments', methods=['GET'])
def get_appointments():
    items, status = query_database(APPOINTMENTS_DB)
    return jsonify(items), status

@app.route('/api/appointments', methods=['POST'])
def create_appointment():
    data = request.get_json() or {}
    props = build_appointment_props(data)
    result, status = create_page(APPOINTMENTS_DB, props)
    return jsonify(result), status

@app.route('/api/appointments/<page_id>', methods=['PUT'])
def update_appointment(page_id):
    data = request.get_json() or {}
    props = build_appointment_props(data)
    result, status = update_page(page_id, props)
    return jsonify(result), status

@app.route('/api/appointments/<page_id>', methods=['DELETE'])
def delete_appointment(page_id):
    result, status = delete_page(page_id)
    return jsonify(result), status

# ===== Routes: Doctors =====
@app.route('/api/doctors', methods=['GET'])
def get_doctors():
    items, status = query_database(DOCTORS_DB)
    return jsonify(items), status

@app.route('/api/doctors', methods=['POST'])
def create_doctor():
    data = request.get_json() or {}
    props = build_doctor_props(data)
    result, status = create_page(DOCTORS_DB, props)
    return jsonify(result), status

@app.route('/api/doctors/<page_id>', methods=['PUT'])
def update_doctor(page_id):
    data = request.get_json() or {}
    props = build_doctor_props(data)
    result, status = update_page(page_id, props)
    return jsonify(result), status

@app.route('/api/doctors/<page_id>', methods=['DELETE'])
def delete_doctor(page_id):
    result, status = delete_page(page_id)
    return jsonify(result), status

# ===== Routes: Medications =====
@app.route('/api/medications', methods=['GET'])
def get_medications():
    items, status = query_database(MEDICATIONS_DB)
    return jsonify(items), status

@app.route('/api/medications', methods=['POST'])
def create_medication():
    data = request.get_json() or {}
    props = build_medication_props(data)
    result, status = create_page(MEDICATIONS_DB, props)
    return jsonify(result), status

@app.route('/api/medications/<page_id>', methods=['PUT'])
def update_medication(page_id):
    data = request.get_json() or {}
    props = build_medication_props(data)
    result, status = update_page(page_id, props)
    return jsonify(result), status

@app.route('/api/medications/<page_id>', methods=['DELETE'])
def delete_medication(page_id):
    result, status = delete_page(page_id)
    return jsonify(result), status

# ===== Health =====
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "version": "v2-notion",
        "time": datetime.now().isoformat(),
        "notion_configured": bool(NOTION_TOKEN and APPOINTMENTS_DB)
    })

# ===== Main =====
if __name__ == '__main__':
    print("⚠️  V2 Notion Backend")
    print(f"   Notion Token: {'✅ Set' if NOTION_TOKEN else '❌ Not set'}")
    print(f"   Appointments DB: {'✅ Set' if APPOINTMENTS_DB else '❌ Not set'}")
    print(f"   Doctors DB: {'✅ Set' if DOCTORS_DB else '❌ Not set'}")
    print(f"   Medications DB: {'✅ Set' if MEDICATIONS_DB else '❌ Not set'}")
    if not NOTION_TOKEN:
        print("\n⚠️  請先設定環境變數：")
        print("   export NOTION_TOKEN='你的Notion API Key'")
        print("   export NOTION_APPOINTMENTS_DB='database_id'")
        print("   export NOTION_DOCTORS_DB='database_id'")
        print("   export NOTION_MEDICATIONS_DB='database_id'")
    app.run(host='0.0.0.0', port=8082, debug=True)
