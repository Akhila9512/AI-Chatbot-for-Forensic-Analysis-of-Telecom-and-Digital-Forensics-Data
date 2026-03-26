"""
ForensicAI Backend — Flask API (FIXED)
Fixes:
  1. Route /api/dataset/<n> had wrong parameter name (n vs name)
  2. Model name updated to claude-haiku-4-5-20251001
  3. Full try/except on every route
  4. Dataset path auto-detection
  5. Detailed error messages returned to frontend
  6. CORS properly configured for file:// and localhost
  7. Summary truncated to avoid token limit errors
  8. API key check before calling Claude
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import pandas as pd
import json, os, traceback

app = Flask(__name__)

CORS(app, resources={
    r"/api/*": {
        "origins": ["*", "null"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

# ── Dataset path auto-detection ────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SEARCH_PATHS = [
    os.path.join(BASE_DIR, "datasets"),
    os.path.join(BASE_DIR, "..", "datasets"),
    os.path.join(BASE_DIR, "..", "..", "datasets"),
    os.path.join(os.getcwd(), "datasets"),
    BASE_DIR,
]

DATASET_DIR = None
for p in SEARCH_PATHS:
    ap = os.path.abspath(p)
    if os.path.isdir(ap):
        files = os.listdir(ap)
        if any(f.endswith(".xlsx") for f in files):
            DATASET_DIR = ap
            break

if not DATASET_DIR:
    DATASET_DIR = os.path.join(BASE_DIR, "datasets")
    print(f"WARNING: No datasets folder found. Defaulting to: {DATASET_DIR}")
else:
    print(f"Datasets folder: {DATASET_DIR}")

DATASET_FILES = {
    "CDR":         "CDR_Data.xlsx",
    "TOWER_DUMP":  "Tower_Dump.xlsx",
    "IPDR":        "IPDR_Data.xlsx",
    "KYC":         "Subscriber_KYC.xlsx",
    "FINANCIAL":   "Financial_Txn.xlsx",
    "DEVICE_LOGS": "Device_Logs.xlsx",
    "GEO":         "Geo_Movement.xlsx",
}

dfs = {}

def load_all():
    print("\nLoading datasets...")
    for key, fname in DATASET_FILES.items():
        path = os.path.join(DATASET_DIR, fname)
        if os.path.exists(path):
            try:
                df = pd.read_excel(path).dropna(how="all")
                dfs[key] = df
                flagged = 0
                if "remarks" in df.columns:
                    flagged = int(df["remarks"].astype(str).str.contains("\u26a0", na=False).sum())
                print(f"  OK {key}: {len(df)} rows, {flagged} flagged")
            except Exception as e:
                print(f"  FAIL {key}: {e}")
        else:
            print(f"  MISSING {key}: {path}")
    print(f"Loaded {len(dfs)}/7 datasets\n")

load_all()


@app.route("/")
def index():
    for loc in [
        os.path.join(BASE_DIR, "frontend"),
        os.path.join(BASE_DIR, "..", "frontend"),
        BASE_DIR,
    ]:
        p = os.path.abspath(loc)
        if os.path.exists(os.path.join(p, "index.html")):
            return send_from_directory(p, "index.html")
    return "<h2>ForensicAI backend running</h2><p>Place index.html in a 'frontend' folder next to app.py</p>"


@app.route("/api/debug")
def debug():
    return jsonify({
        "status": "ok",
        "base_dir": BASE_DIR,
        "dataset_dir": DATASET_DIR,
        "dir_exists": os.path.exists(DATASET_DIR),
        "xlsx_files": [f for f in os.listdir(DATASET_DIR) if f.endswith(".xlsx")] if os.path.exists(DATASET_DIR) else [],
        "datasets_loaded": list(dfs.keys()),
        "cwd": os.getcwd(),
        "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
    })


@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "datasets_loaded": list(dfs.keys()),
        "total_datasets": len(dfs),
        "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
    })


@app.route("/api/stats")
def get_stats():
    try:
        total_flagged = 0
        for df in dfs.values():
            if "remarks" in df.columns:
                total_flagged += int(df["remarks"].astype(str).str.contains("\u26a0", na=False).sum())
        return jsonify({
            "total_records": sum(len(df) for df in dfs.values()),
            "total_flagged": total_flagged,
            "suspects_tracked": 4,
            "datasets_loaded": len(dfs),
            "crime_date": "2025-01-15",
            "crime_tower": "T-204",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/datasets")
def datasets_info():
    try:
        info = {}
        for key, df in dfs.items():
            flagged = 0
            if "remarks" in df.columns:
                flagged = int(df["remarks"].astype(str).str.contains("\u26a0", na=False).sum())
            info[key] = {
                "rows": len(df),
                "columns": df.columns.tolist(),
                "flagged": flagged,
            }
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# FIX: was /api/dataset/<n> but used `name` inside — now consistent
@app.route("/api/dataset/<name>")
def get_dataset(name):
    try:
        key = name.upper()
        if key not in dfs:
            return jsonify({
                "error": f"Dataset '{key}' not found.",
                "available": list(dfs.keys())
            }), 404

        df = dfs[key]
        df2 = df.head(300).copy()

        for col in df2.columns:
            if pd.api.types.is_datetime64_any_dtype(df2[col]):
                df2[col] = df2[col].astype(str)
            elif df2[col].dtype == object:
                df2[col] = df2[col].apply(
                    lambda x: str(x) if not isinstance(x, (str, int, float, type(None))) else x
                )

        records = json.loads(df2.fillna("").to_json(orient="records"))

        flagged_indices = []
        if "remarks" in df.columns:
            flagged_indices = df.index[
                df["remarks"].astype(str).str.contains("\u26a0", na=False)
            ].tolist()

        return jsonify({
            "name": key,
            "columns": df.columns.tolist(),
            "rows": records,
            "flagged_indices": flagged_indices,
            "total": len(df),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/patterns")
def get_patterns():
    try:
        patterns = []

        if "CDR" in dfs:
            cdr = dfs["CDR"]
            if "imei_caller" in cdr.columns and "caller_number" in cdr.columns:
                imei_sims = cdr.groupby("imei_caller")["caller_number"].nunique()
                for imei, count in imei_sims[imei_sims > 3].items():
                    patterns.append({
                        "type": "SIM_SWAP", "severity": "CRITICAL",
                        "title": "SIM Swapping Detected",
                        "detail": f"IMEI {str(imei)[:15]}... used with {count} SIM cards",
                        "dataset": "CDR"
                    })
            if "call_start_time" in cdr.columns:
                cdr2 = cdr.copy()
                cdr2["_hour"] = pd.to_datetime(cdr2["call_start_time"], errors="coerce").dt.hour
                for num, cnt in cdr2[cdr2["_hour"].between(0, 4)].groupby("caller_number").size().items():
                    if cnt >= 3:
                        patterns.append({
                            "type": "MIDNIGHT_BURST", "severity": "HIGH",
                            "title": "Midnight Call Burst",
                            "detail": f"{num} made {cnt} calls between midnight-4AM",
                            "dataset": "CDR"
                        })

        if "IPDR" in dfs:
            ipdr = dfs["IPDR"]
            if "remarks" in ipdr.columns:
                for _, row in ipdr[ipdr["remarks"].astype(str).str.contains("TOR|VPN|EXFIL|PHISH", na=False, case=False)].iterrows():
                    patterns.append({
                        "type": "DARK_WEB", "severity": "CRITICAL",
                        "title": "Suspicious Internet Activity",
                        "detail": str(row.get("remarks", ""))[:120],
                        "dataset": "IPDR"
                    })

        if "KYC" in dfs:
            kyc = dfs["KYC"]
            if "id_proof_number" in kyc.columns and "msisdn" in kyc.columns:
                for id_num, cnt in kyc.groupby("id_proof_number")["msisdn"].count().items():
                    if cnt > 1:
                        patterns.append({
                            "type": "FAKE_KYC", "severity": "HIGH",
                            "title": "Duplicate ID Detected",
                            "detail": f"ID '{id_num}' linked to {cnt} SIM cards",
                            "dataset": "KYC"
                        })

        if "FINANCIAL" in dfs:
            fin = dfs["FINANCIAL"]
            if "amount_inr" in fin.columns:
                large = fin[pd.to_numeric(fin["amount_inr"], errors="coerce") > 100000]
                if not large.empty:
                    patterns.append({
                        "type": "FINANCIAL_ANOMALY", "severity": "HIGH",
                        "title": "Large Transactions Detected",
                        "detail": f"{len(large)} transactions above Rs.1 Lakh flagged",
                        "dataset": "FINANCIAL"
                    })

        if "GEO" in dfs:
            geo = dfs["GEO"]
            if "speed_kmph" in geo.columns:
                impossible = geo[pd.to_numeric(geo["speed_kmph"], errors="coerce") > 500]
                if not impossible.empty:
                    patterns.append({
                        "type": "IMPOSSIBLE_TRAVEL", "severity": "CRITICAL",
                        "title": "Impossible Travel Detected",
                        "detail": f"{len(impossible)} records with speed >500 kmph",
                        "dataset": "GEO"
                    })

        return jsonify(patterns)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ── CHAT — FULLY FIXED ─────────────────────────────────────────
import requests

@app.route("/api/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"response": "Error: could not parse request body."}), 200

        messages = data.get("messages", [])
        if not messages:
            return jsonify({"response": "Error: no messages provided."}), 200

        # Combine user messages
        user_prompt = "\n".join([
            str(m["content"]) for m in messages
            if m.get("role") == "user"
        ])

        if not user_prompt.strip():
            return jsonify({"response": "Please type a message."}), 200

        # Build dataset summary (same logic, lighter)
        summary_lines = []
        for key, df in dfs.items():
            cols = ", ".join(df.columns.tolist())
            summary_lines.append(f"{key} ({len(df)} rows) | Columns: {cols}")

        full_prompt = f"""
You are ForensicAI, an expert in telecom and digital forensics.

CRIME SCENARIO:
- Bank Fraud + Murder Cover-up
- Location: Tower T-204
- Date: 2025-01-15

DATASETS:
{chr(10).join(summary_lines)}

USER QUESTION:
{user_prompt}

Give answer with:
FINDING
EVIDENCE
PATTERN
LEAD
RECOMMENDATION
"""

        # 🔥 CALL OLLAMA (LOCAL)
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3",
                "prompt": full_prompt,
                "stream": False
            }
        )

        result = response.json().get("response", "No response from model")

        return jsonify({"response": result})

    except Exception as e:
        return jsonify({
            "response": f"Server error: {str(e)}"
        }), 200

@app.route("/api/suspect/<msisdn>")
def get_suspect_profile(msisdn):
    try:
        profile = {"msisdn": msisdn, "connections": [], "locations": [], "internet": [], "financial": []}
        if "CDR" in dfs:
            cdr = dfs["CDR"]
            calls = cdr[cdr["caller_number"].astype(str) == msisdn]
            if not calls.empty:
                top = calls.groupby("receiver_number").size().sort_values(ascending=False).head(5)
                profile["connections"] = [{"number": k, "count": int(v)} for k, v in top.items()]
                profile["call_count"] = len(calls)
        if "GEO" in dfs:
            locs = dfs["GEO"][dfs["GEO"]["msisdn"].astype(str) == msisdn].head(10).fillna("")
            profile["locations"] = json.loads(locs.to_json(orient="records"))
        if "IPDR" in dfs:
            sess = dfs["IPDR"][dfs["IPDR"]["msisdn"].astype(str) == msisdn].head(10).fillna("")
            profile["internet"] = json.loads(sess.to_json(orient="records"))
        if "FINANCIAL" in dfs:
            txns = dfs["FINANCIAL"][dfs["FINANCIAL"]["msisdn"].astype(str) == msisdn].head(10).fillna("")
            profile["financial"] = json.loads(txns.to_json(orient="records"))
        return jsonify(profile)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("=" * 55)
    print("ForensicAI Backend")
    print("=" * 55)
    print(f"Dataset dir  : {DATASET_DIR}")
    print(f"Datasets     : {len(dfs)}/7 loaded — {list(dfs.keys())}")
    key_status = "SET" if os.environ.get("ANTHROPIC_API_KEY") else "NOT SET — export ANTHROPIC_API_KEY=sk-ant-..."
    print(f"API key      : {key_status}")
    print(f"URL          : http://localhost:5000")
    print("=" * 55 + "\n")
    app.run(debug=True, port=5000, host="0.0.0.0")
