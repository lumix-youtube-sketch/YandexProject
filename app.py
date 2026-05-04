import os
import uuid
import functools
import random
import requests
from datetime import date, timedelta, datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
BASE_DIR = os.path.dirname(os.path.abspath(__file__))



# конфиг
class Config:
    SECRET_KEY = "habit-tracker-secret-2024"
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "habits.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16

    #какие файлы можно загружать
    ALLOWED_IMAGE = {"png","jpg","jpeg","gif","webp"}
    ALLOWED_AUDIO = {"mp3", "ogg", "wav"}


# создаем приложение
app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy()
db.init_app(app)

# создаем папку для загрузок если её нет
if not os.path.exists(app.config["UPLOAD_FOLDER"]):
    os.makedirs(app.config["UPLOAD_FOLDER"])


# таблицы

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    avatar_filename = db.Column(db.String(256), nullable=True)
    music_filename = db.Column(db.String(256), nullable=True)
    created_at = db.Column(db.Date, default=date.today, nullable=False)
    habits = db.relationship("Habit", backref="user", lazy=True, cascade="all, delete-orphan")
    tasks = db.relationship("Task", backref="user", lazy=True, cascade="all, delete-orphan")
    notes = db.relationship("Note", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Habit(db.Model):
    __tablename__ = "habits"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    color = db.Column(db.String(7), nullable=False, default="#6366f1")
    created_at = db.Column(db.Date, default=date.today, nullable=False)
    completions = db.relationship("Completion", backref="habit", lazy=True, cascade="all, delete-orphan")

    def completion_dates(self):
        # все даты выполнений в виде строк
        result = []
        for c in self.completions:
            result.append(c.date.isoformat())
        return result

    def streak(self):
        # сколько дней подряд (считаем от сегодня назад пока есть отметки)
        dates = set(self.completion_dates())
        count = 0
        d = date.today()
        while d.isoformat() in dates:
            count = count + 1
            d = d - timedelta(days=1)
        return count

    def to_dict(self):
        # для js
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "completions": self.completion_dates(),
        }


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    done = db.Column(db.Boolean, default=False, nullable=False)
    priority = db.Column(db.String(10), default="medium", nullable=False)
    deadline = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=date.today, nullable=False)


    def is_overdue(self):
        if self.deadline is None:
            return False
        if self.done == True:
            return False
        if self.deadline < date.today():
            return True
        return False


class Note(db.Model):
    __tablename__ = "notes"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False, default="")
    updated_at = db.Column(db.DateTime, default=date.today, nullable=False)
    created_at = db.Column(db.DateTime, default=date.today, nullable=False)


class Completion(db.Model):
    __tablename__ = "completions"
    id = db.Column(db.Integer, primary_key=True)
    habit_id = db.Column(db.Integer, db.ForeignKey("habits.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    # одна привычка - одна отметка в день
    __table_args__ = (db.UniqueConstraint("habit_id", "date", name="uq_habit_date"),)


# доп функции

def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return redirect(url_for("login"))
        user = db.session.get(User, user_id)
        if user is None:
            session.pop("user_id", None)
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def current_user():
    if "user_id" not in session:
        return None
    return db.session.get(User, session["user_id"])


def get_last_7_days():
    # 7 дней включая сегодня
    today = date.today()
    days = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        days.append(day.isoformat())
    return days


def allowed_file(filename, allowed):
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    if ext in allowed:
        return True
    else:
        return False


def save_upload(file, allowed):
    # сохраняем с рандомным именем
    if not file:
        return None
    if file.filename == "":
        return None
    if not allowed_file(file.filename, allowed):
        return None
    ext = file.filename.rsplit(".", 1)[1].lower()
    filename = uuid.uuid4().hex + "." + ext
    full_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(full_path)
    return filename


def remove_upload(filename):
    if not filename:
        return
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if os.path.exists(path):
        try:
            os.remove(path)
        except:
            pass


# на случай если api с цитатами не отвечает
QUOTES = [
    {"text": "Дисциплина важнее мотивации", "author": ""},
    {"text": "Сначала тяжело, потом привычка", "author": ""},
    {"text":"Ты — это то, что ты делаешь каждый день", "author": ""},
]


def fetch_quote():
    try:
        resp = requests.get(
            "http://api.forismatic.com/api/1.0/?method=getQuote&format=json&lang=ru",
            timeout=2
        )
        data = resp.json()
        text = data.get("quoteText", "").strip()
        if text == "":
            return random.choice(QUOTES)
        return {
            "text": text,
            "author": data.get("quoteAuthor", "").strip()
        }
    except:
        return random.choice(QUOTES)



@app.route("/")
@login_required
def index():
    user = current_user()
    days = get_last_7_days()
    spisok = []
    for h in user.habits:
        spisok.append(h.to_dict())
    cit = fetch_quote()
    return render_template(
        "index.html",
        user=user,
        habits=user.habits,
        habits_json=spisok,
        days=days,
        today=date.today().isoformat(),
        quote=cit,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("index"))

    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == "" or password == "":
            error = "Заполни все поля"
        elif len(username) < 3:
            error = "Имя пользователя — минимум 3 символа"
        elif len(password) < 4:
            error = "Пароль — минимум 4 символа"
        else:
            existing = User.query.filter_by(username=username).first()
            if existing is not None:
                error = "Пользователь уже существует"
            else:
                u = User(username=username)
                u.set_password(password)
                db.session.add(u)

                try:
                    db.session.commit()
                except IntegrityError:
                    # на всякий случай если две регистрации одновременно
                    db.session.rollback()
                    error = "Пользователь уже существует"
                else:
                    session["user_id"] = u.id
                    return redirect(url_for("index"))

    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))

    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        # одинаковый текст ошибки чтобы не палить какие логины существуют
        if user is None:
            error = "Неверное имя пользователя или пароль"
        elif not user.check_password(password):
            error = "Неверное имя пользователя или пароль"
        else:
            session["user_id"] = user.id
            return redirect(url_for("index"))

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user()
    error = None
    success = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "avatar":
            avatar_file = request.files.get("avatar")
            gg1 = save_upload(avatar_file, app.config["ALLOWED_IMAGE"])

            if gg1 is not None:
                # удаляем старый
                remove_upload(user.avatar_filename)
                user.avatar_filename = gg1
                db.session.commit()
                return redirect(url_for("profile", msg="avatar"))
            else:
                error = "Недопустимый формат. Разрешены: png, jpg, jpeg, gif, webp"

        elif action == "music":
            music_file = request.files.get("music")
            gg2 = save_upload(music_file, app.config["ALLOWED_AUDIO"])

            if gg2 is not None:
                remove_upload(user.music_filename)
                user.music_filename = gg2
                db.session.commit()
                return redirect(url_for("profile", msg="music"))
            else:
                error = "Недопустимый формат. Разрешены: mp3, ogg, wav"

        elif action == "delete_music":
            remove_upload(user.music_filename)
            user.music_filename = None
            db.session.commit()
            return redirect(url_for("profile", msg="del_music"))

        elif action == "password":
            staryi = request.form.get("current_password", "")
            novyi = request.form.get("new_password", "")

            if not user.check_password(staryi):
                error = "Неверный текущий пароль"
            elif len(novyi) < 4:
                error = "Новый пароль — минимум 4 символа"
            else:
                user.set_password(novyi)
                db.session.commit()
                return redirect(url_for("profile", msg="password"))

    # сообщения после редиректа
    msg = request.args.get("msg")
    if msg == "avatar":
        success = "Аватар обновлён"
    elif msg == "music":
        success = "Музыка обновлена"
    elif msg == "del_music":
        success = "Музыка удалена"
    elif msg == "password":
        success = "Пароль изменён"

    db.session.expire_all()
    user = current_user()

    # считаем сколько всего выполнений
    vsego = 0
    for habit in user.habits:
        vsego = vsego + len(habit.completions)

    return render_template(
        "profile.html",
        user=user,
        error=error,
        success=success,
        total_completions=vsego,
    )


@app.route("/add", methods=["POST"])
@login_required
def add_habit():
    name = request.form.get("name", "").strip()
    color = request.form.get("color", "#6366f1")

    if name != "":
        user = current_user()
        habit = Habit(user_id=user.id, name=name, color=color)
        db.session.add(habit)
        db.session.commit()

    return redirect(url_for("index"))


@app.route("/delete/<int:habit_id>", methods=["POST"])
@login_required
def delete_habit(habit_id):
    user = current_user()
    habit = Habit.query.filter_by(id=habit_id, user_id=user.id).first()
    if habit is not None:
        db.session.delete(habit)
        db.session.commit()
    return redirect(url_for("index"))


@app.route("/toggle", methods=["POST"])
@login_required
def toggle():
    body = request.get_json()
    habit_id = body.get("habit_id")
    day_str = body.get("day")
    user = current_user()
    habit = Habit.query.filter_by(id=habit_id, user_id=user.id).first()
    if habit is None:
        return jsonify({"error": "not found"}), 404
    try:
        day = date.fromisoformat(day_str)
    except:
        return jsonify({"error": "bad date"}), 400

    otmetka = Completion.query.filter_by(habit_id=habit.id, date=day).first()

    if otmetka is not None:
        db.session.delete(otmetka)
        db.session.commit()
        gotovo = False
    else:
        novaya = Completion(habit_id=habit.id, date=day)
        db.session.add(novaya)
        db.session.commit()
        gotovo = True
    return jsonify({"done": gotovo, "streak": habit.streak()})


@app.route("/tasks")
@login_required
def tasks():
    user = current_user()
    filter_by = request.args.get("filter", "all")
    q = Task.query.filter_by(user_id=user.id)
    if filter_by == "active":
        q = q.filter_by(done=False)
    elif filter_by == "done":
        q = q.filter_by(done=True)

    # сначала невыполненные сверху, потом по дате
    spisok = q.order_by(Task.done.asc(), Task.created_at.desc()).all()

    total = Task.query.filter_by(user_id=user.id).count()
    done_count = Task.query.filter_by(user_id=user.id, done=True).count()

    return render_template(
        "tasks.html",
        user=user,
        tasks=spisok,
        filter_by=filter_by,
        total=total,
        done_count=done_count,
        today=date.today(),
    )


@app.route("/tasks/add", methods=["POST"])
@login_required
def add_task():
    title = request.form.get("title", "").strip()
    priority = request.form.get("priority", "medium")
    deadline_str = request.form.get("deadline", "").strip()
    deadline = None
    if deadline_str != "":
        try:
            deadline = date.fromisoformat(deadline_str)
        except:
            deadline = None
    prio_ok = ("low", "medium", "high")
    if title != "" and priority in prio_ok:
        user = current_user()
        t = Task(user_id=user.id, title=title, priority=priority, deadline=deadline)
        db.session.add(t)
        db.session.commit()
    return redirect(url_for("tasks"))


@app.route("/tasks/toggle/<int:task_id>", methods=["POST"])
@login_required
def toggle_task(task_id):
    user = current_user()
    task = Task.query.filter_by(id=task_id, user_id=user.id).first()
    if task is not None:
        if task.done:
            task.done = False
        else:
            task.done = True
        db.session.commit()
    f = request.form.get("filter", "all")
    return redirect(url_for("tasks", filter=f))


@app.route("/tasks/delete/<int:task_id>", methods=["POST"])
@login_required
def delete_task(task_id):
    user = current_user()
    task = Task.query.filter_by(id=task_id, user_id=user.id).first()
    if task is not None:
        db.session.delete(task)
        db.session.commit()
    f = request.form.get("filter", "all")
    return redirect(url_for("tasks", filter=f))


@app.route("/notes")
@login_required
def notes():
    user = current_user()
    spisok = Note.query.filter_by(user_id=user.id).order_by(Note.updated_at.desc()).all()
    return render_template("notes.html", user=user, notes=spisok)


@app.route("/notes/add", methods=["POST"])
@login_required
def add_note():
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    if title != "":
        user = current_user()
        n = Note(user_id=user.id, title=title, content=content)
        db.session.add(n)
        db.session.commit()
    return redirect(url_for("notes"))


@app.route("/notes/edit/<int:note_id>", methods=["GET", "POST"])
@login_required
def edit_note(note_id):
    user = current_user()
    note = Note.query.filter_by(id=note_id, user_id=user.id).first_or_404()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        if title != "":
            note.title = title
            note.content = content
            note.updated_at = datetime.now()
            db.session.commit()
        return redirect(url_for("notes"))
    return render_template("note_edit.html", user=user, note=note)


@app.route("/notes/delete/<int:note_id>", methods=["POST"])
@login_required
def delete_note(note_id):
    user = current_user()
    note = Note.query.filter_by(id=note_id, user_id=user.id).first()
    if note is not None:
        db.session.delete(note)
        db.session.commit()
    return redirect(url_for("notes"))


# создаем таблицы при первом запуске
with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)
