from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import json
import os
from datetime import date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import functools

app = Flask(__name__)
app.secret_key = "habit-tracker-secret-key-2024"
DATA_FILE = "data.json"


def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}}
    with open(DATA_FILE) as f:
        data = json.load(f)
    if "habits" in data and "users" not in data:
        return {"users": {}}
    return data


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_user_habits(data, username):
    return data["users"].get(username, {}).get("habits", [])


def get_last_7_days():
    today = date.today()
    return [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/")
@login_required
def index():
    data = load_data()
    habits = get_user_habits(data, session["username"])
    days = get_last_7_days()
    return render_template("index.html", habits=habits, days=days,
                           today=date.today().isoformat(), username=session["username"])


@app.route("/register", methods=["GET", "POST"])
def register():
    if "username" in session:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            error = "Заполни все поля"
        elif len(username) < 3:
            error = "Имя пользователя — минимум 3 символа"
        elif len(password) < 4:
            error = "Пароль — минимум 4 символа"
        else:
            data = load_data()
            if username in data["users"]:
                error = "Пользователь уже существует"
            else:
                data["users"][username] = {
                    "password_hash": generate_password_hash(password),
                    "habits": []
                }
                save_data(data)
                session["username"] = username
                return redirect(url_for("index"))
    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    if "username" in session:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        data = load_data()
        user = data["users"].get(username)
        if not user or not check_password_hash(user["password_hash"], password):
            error = "Неверное имя пользователя или пароль"
        else:
            session["username"] = username
            return redirect(url_for("index"))
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("login"))


@app.route("/add", methods=["POST"])
@login_required
def add_habit():
    name = request.form.get("name", "").strip()
    color = request.form.get("color", "#6366f1")
    if name:
        data = load_data()
        username = session["username"]
        data["users"][username]["habits"].append({
            "id": int(date.today().strftime("%Y%m%d%H%M%S")),
            "name": name,
            "color": color,
            "completions": []
        })
        save_data(data)
    return redirect(url_for("index"))


@app.route("/delete/<int:habit_id>", methods=["POST"])
@login_required
def delete_habit(habit_id):
    data = load_data()
    username = session["username"]
    data["users"][username]["habits"] = [
        h for h in data["users"][username]["habits"] if h["id"] != habit_id
    ]
    save_data(data)
    return redirect(url_for("index"))


@app.route("/toggle", methods=["POST"])
@login_required
def toggle():
    body = request.get_json()
    habit_id = body["habit_id"]
    day = body["day"]
    data = load_data()
    username = session["username"]
    for habit in data["users"][username]["habits"]:
        if habit["id"] == habit_id:
            if day in habit["completions"]:
                habit["completions"].remove(day)
                done = False
            else:
                habit["completions"].append(day)
                done = True
            save_data(data)
            streak = compute_streak(habit["completions"])
            return jsonify({"done": done, "streak": streak})
    return jsonify({"error": "not found"}), 404


def compute_streak(completions):
    if not completions:
        return 0
    today = date.today()
    streak = 0
    d = today
    while d.isoformat() in completions:
        streak += 1
        d -= timedelta(days=1)
    return streak


if __name__ == "__main__":
    app.run(debug=True)
