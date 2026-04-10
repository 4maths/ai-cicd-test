from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return "Hello AI CICD", 200

@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

# endpoint để test latency (optional)
@app.route("/slow")
def slow():
    import time
    time.sleep(2)
    return jsonify({"status": "ok", "note": "slow"}), 200

if __name__ == "__main__":
    # QUAN TRỌNG: bind 0.0.0.0 để có thể gọi từ ngoài container/VM (sau này)
    app.run(host="0.0.0.0", port=8000)