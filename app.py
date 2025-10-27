from flask import Flask, request

app = Flask(__name__)

@app.route('/')
def index():
    return f"Hello, this is Flask without a real server! Method: {request.method}"

@app.route('/add', methods=['POST'])
def add():
    data = request.get_json(force=True)
    return {"sum": data["a"] + data["b"]}
