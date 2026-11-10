import os, sqlite3, secrets, re
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
ROOT = os.path.dirname(os.path.abspath(__file__))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=False)
except ImportError:
    pass

DB = os.path.join(ROOT, "inclulearn.db")
UPLOAD = os.path.join(ROOT, "uploads")
os.makedirs(UPLOAD, exist_ok=True)
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-before-deploy")
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
ALLOWED = {"txt", "pdf", "docx"}

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS materials(id INTEGER PRIMARY KEY, teacher_id INTEGER, title TEXT, grade INTEGER, subject TEXT, topic TEXT, original TEXT, adapted TEXT, support TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS assignments(id INTEGER PRIMARY KEY, material_id INTEGER, teacher_id INTEGER, class_name TEXT, criteria TEXT, status TEXT DEFAULT 'assigned', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS submissions(id INTEGER PRIMARY KEY, assignment_id INTEGER, student_id INTEGER, answer TEXT, ai_feedback TEXT, proposed_score REAL, teacher_score REAL, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY, name TEXT, email TEXT, category TEXT, message TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS textbooks(id INTEGER PRIMARY KEY, grade INTEGER, subject TEXT, language TEXT, title TEXT, publisher TEXT, year TEXT, source_url TEXT, topics TEXT DEFAULT '', verified INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS rubrics(id INTEGER PRIMARY KEY, teacher_id INTEGER, title TEXT, subject TEXT, grade INTEGER, criteria TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS ai_chats(id INTEGER PRIMARY KEY, user_id INTEGER, question TEXT, answer TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS textbook_topics(id INTEGER PRIMARY KEY, textbook_id INTEGER, topic TEXT, objective TEXT DEFAULT '');
    """)
    # Demo admin account. Change password after first login.
    if not c.execute("SELECT id FROM users WHERE email=?", ("admin@inclulearn.local",)).fetchone():
        c.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)",
                  ("Әкімші", "admin@inclulearn.local", generate_password_hash("Admin123!"), "admin"))
    c.commit()
    c.close()

SUBJECTS = ["Қазақ тілі","Қазақ әдебиеті","Орыс тілі","Орыс әдебиеті","Ағылшын тілі","Математика","Алгебра","Геометрия","Информатика","Қазақстан тарихы","Дүниежүзі тарихы","Жаратылыстану","Физика","Химия","Биология","География","Көркем еңбек","Музыка","Дене шынықтыру","Адам. Қоғам. Құқық"]
def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("uid"): return redirect(url_for("login"))
        return f(*a, **k)
    return w
def role_required(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if session.get("role") not in roles: flash("Бұл бөлімге рұқсатыңыз жоқ.", "error"); return redirect(url_for("dashboard"))
            return f(*a, **k)
        return w
    return deco

@app.route("/")
def home():
    if session.get("uid"): return redirect(url_for("dashboard"))
    return render_template("home.html")
@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name=request.form.get("name","").strip(); email=request.form.get("email","").strip().lower()
        pw=request.form.get("password",""); role=request.form.get("role","teacher")
        if role not in ("teacher","student"): role="student"
        if not name or not email or len(pw)<8: flash("Барлық өрісті толтырыңыз. Құпиясөз кемінде 8 таңба болсын.","error")
        else:
            c=db()
            try:
                c.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)",(name,email,generate_password_hash(pw),role)); c.commit()
                flash("Тіркелу сәтті аяқталды. Енді кіріңіз.","success"); return redirect(url_for("login"))
            except sqlite3.IntegrityError: flash("Бұл email тіркелген.","error")
            finally: c.close()
    return render_template("auth.html", mode="register")
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        c=db(); u=c.execute("SELECT * FROM users WHERE email=?",(request.form.get("email","").lower(),)).fetchone(); c.close()
        if u and check_password_hash(u["password"],request.form.get("password","")):
            session.update(uid=u["id"],name=u["name"],role=u["role"]); return redirect(url_for("dashboard"))
        flash("Email немесе құпиясөз қате.","error")
    return render_template("auth.html",mode="login")
@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("home"))
@app.route("/dashboard")
@login_required
def dashboard():
    c=db()
    if session["role"]=="student":
        rows=c.execute("""SELECT a.*,m.title,m.grade,m.subject,m.topic,u.name teacher FROM assignments a JOIN materials m ON m.id=a.material_id JOIN users u ON u.id=a.teacher_id LEFT JOIN submissions s ON s.assignment_id=a.id AND s.student_id=? WHERE s.id IS NULL OR s.student_id=? ORDER BY a.id DESC""",(session["uid"],session["uid"])).fetchall()
    else:
        rows=c.execute("""SELECT a.*,m.title,m.grade,m.subject,m.topic FROM assignments a JOIN materials m ON m.id=a.material_id WHERE a.teacher_id=? ORDER BY a.id DESC""",(session["uid"],)).fetchall()
        materials=c.execute("SELECT * FROM materials WHERE teacher_id=? ORDER BY id DESC LIMIT 12",(session["uid"],)).fetchall()
    if session["role"]=="student": materials=[]
    c.close()
    return render_template("dashboard.html",rows=rows,materials=materials)
@app.route("/adapt",methods=["GET","POST"])
@login_required
@role_required("teacher","admin")
def adapt():
    if request.method=="POST":
        title=request.form.get("title","Материал").strip(); grade=int(request.form.get("grade",7)); subject=request.form.get("subject","Информатика"); topic=request.form.get("topic","")
        original=request.form.get("content","").strip(); support=", ".join(request.form.getlist("support"))
        f=request.files.get("file")
        if f and f.filename:
            ext=f.filename.rsplit(".",1)[-1].lower()
            if ext not in ALLOWED: flash("Тек TXT, PDF немесе DOCX файлдары қабылданады.","error"); return redirect(url_for("adapt"))
            path=os.path.join(UPLOAD,secrets.token_hex(8)+"_"+secure_filename(f.filename)); f.save(path)
            if ext=="txt":
                original += "\n"+open(path,encoding="utf-8",errors="ignore").read()
            elif ext=="pdf":
                try:
                    import pypdf
                    reader=pypdf.PdfReader(path); original += "\n"+"\n".join(p.extract_text() or "" for p in reader.pages)
                except Exception: flash("PDF мәтінін оқу мүмкін болмады. Мәтінді қолмен енгізіңіз.","error")
            elif ext=="docx":
                try:
                    from docx import Document
                    original += "\n"+"\n".join(p.text for p in Document(path).paragraphs)
                except Exception: flash("DOCX файлын оқу мүмкін болмады.","error")
        if not original: flash("Мәтін енгізіңіз немесе файл жүктеңіз.","error"); return redirect(url_for("adapt"))
        try:
            adapted=adapt_text(original,support,grade,subject,topic)
        except Exception as e:
            app.logger.exception("Claude adaptation failed")
            flash("Claude арқылы бейімдеу орындалмады: "+str(e)[:220],"error")
            return redirect(url_for("adapt"))
        c=db(); cur=c.execute("INSERT INTO materials(teacher_id,title,grade,subject,topic,original,adapted,support) VALUES(?,?,?,?,?,?,?,?)",(session["uid"],title,grade,subject,topic,original,adapted,support)); mid=cur.lastrowid; c.commit(); c.close()
        return redirect(url_for("material",mid=mid))
    return render_template("adapt.html",subjects=SUBJECTS)
def ai_generate(system_prompt, user_prompt, max_chars=24000):
    """Generate content only through the configured Anthropic Claude API."""
    key=os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise ValueError("ANTHROPIC_API_KEY .env файлында көрсетілмеген")
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic SDK орнатылмаған. python3 -m pip install -r requirements.txt орындаңыз.") from exc
    model=os.environ.get("AI_MODEL", "claude-sonnet-5-5").strip()
    client=Anthropic(api_key=key)
    response=client.messages.create(
        model=model,
        max_tokens=5000,
        system=system_prompt,
        messages=[{"role":"user", "content":user_prompt[:max_chars]}]
    )
    result="\n".join(block.text for block in response.content if getattr(block, "type", None)=="text").strip()
    if len(result)<120:
        raise RuntimeError("Claude жауабы тым қысқа немесе бос")
    return result

def adapt_text(text,support,grade,subject="",topic=""):
    if not text or len(text.strip())<30: raise ValueError("Материал тым қысқа. Кемінде 30 таңба енгізіңіз")
    instructions=f"""Сен Қазақстан мектебіне арналған тәжірибелі пән мұғалімі, әдіскер және инклюзивті педагогсің. {grade}-сынып, пән: {subject}, тақырып: {topic or 'мәтіннен анықта'}. Оқушыға қажет қолдау: {support or 'түсінікті құрылымды тіл'}.
МІНДЕТ: берілген бастапқы материал негізінде сабақта бірден қолдануға болатын сапалы, толық және нақты бейімделген оқу материалын жаса. Тек бастапқы мәтіндегі дәлелденген ақпаратты пайдалан; деректерді, анықтамаларды, пәндік терминдерді, формулаларды, даталарды және себеп-салдар байланыстарын бұрмалама. Жоқ ақпаратты ойдан қоспа. Күрделі сөйлемдерді қысқарт, бір сөйлемде бір негізгі ой бер, жаңа терминді қарапайым тілмен түсіндір. Бейімдеу оқушының жасына және сынып деңгейіне сай болсын, бірақ оқу мақсаты мен пәндік мазмұн жеңілдету кезінде жоғалмасын.
МІНДЕТТІ ҚҰРЫЛЫМ: 1) Тақырып; 2) нақты оқу мақсаты; 3) негізгі ұғымдар мен қысқа сөздік; 4) кезең-кезеңімен түсіндіру; 5) мазмұнға дәл сәйкес мысал; 6) үш деңгейдегі тапсырмалар (жеңіл, орта, күрделі), жауаптары емес, орындау нұсқаулығымен; 7) өзін-өзі тексеруге арналған 3-5 сұрақ; 8) мұғалімге ескерту және қажет болса тексерілуі тиіс тұстар.
Қолдау түріне сай форматта: {support or 'қысқа абзацтар, нақты қадамдар және түсінікті тіл'}. Тапсырмалар оқу мақсатына тікелей сәйкес болсын. Бастапқы мәтінді тұтас көшірме. Нәтижені сауатты қазақ тілінде, тақырыпшалармен және оқуға ыңғайлы ретпен жаз."""
    result=ai_generate(instructions,"ОҚУ МАТЕРИАЛЫ:\n"+text)
    if result.strip()==text.strip(): raise RuntimeError("AI бастапқы мәтінді өзгертпеді")
    return result

@app.route("/material/<int:mid>")
@login_required
def material(mid):
    c=db(); m=c.execute("SELECT * FROM materials WHERE id=?",(mid,)).fetchone(); c.close()
    if not m: return "Материал табылмады",404
    if session.get("role") not in ("admin",) and session.get("role")!="student" and m["teacher_id"]!=session.get("uid"): return "Қолжетімділік жоқ",403
    return render_template("material.html",m=m)
@app.route("/assign/<int:mid>",methods=["POST"])
@login_required
@role_required("teacher","admin")
def assign(mid):
    c=db(); c.execute("INSERT INTO assignments(material_id,teacher_id,class_name,criteria) VALUES(?,?,?,?)",(mid,session["uid"],request.form.get("class_name",""),request.form.get("criteria",""))); c.commit(); c.close()
    flash("Материал тапсырма ретінде жарияланды.","success"); return redirect(url_for("dashboard"))
@app.route("/assignment/<int:aid>",methods=["GET","POST"])
@login_required
def assignment(aid):
    c=db(); a=c.execute("SELECT a.*,m.title,m.adapted,m.grade,m.subject FROM assignments a JOIN materials m ON m.id=a.material_id WHERE a.id=?",(aid,)).fetchone()
    if not a: c.close(); return "Тапсырма табылмады",404
    if request.method=="POST" and session["role"]=="student":
        answer=request.form.get("answer","").strip()
        c.execute("INSERT INTO submissions(assignment_id,student_id,answer,ai_feedback,proposed_score) VALUES(?,?,?,?,?)",(aid,session["uid"],answer,"Жауап мұғалімнің критерийлері бойынша тексеруге жіберілді.",None)); c.commit(); flash("Жауап жіберілді.","success")
    subs=c.execute("SELECT s.*,u.name student FROM submissions s JOIN users u ON u.id=s.student_id WHERE assignment_id=?",(aid,)).fetchall() if session["role"] in ("teacher","admin") else []
    c.close(); return render_template("assignment.html",a=a,subs=subs)
@app.route("/review/<int:sid>",methods=["POST"])
@login_required
@role_required("teacher","admin")
def review(sid):
    score=request.form.get("score"); feedback=request.form.get("feedback","")
    c=db(); c.execute("UPDATE submissions SET teacher_score=?,ai_feedback=?,status='reviewed' WHERE id=?",(score,feedback,sid)); c.commit(); c.close()
    flash("Мұғалім бағалауы сақталды.","success"); return redirect(request.referrer or url_for("dashboard"))
@app.route("/textbooks")
@login_required
def textbooks():
    grade=request.args.get("grade"); subject=request.args.get("subject"); lang=request.args.get("language","kk")
    c=db(); rows=c.execute("SELECT * FROM textbooks WHERE (?='' OR grade=?) AND (?='' OR subject=?) AND language=? ORDER BY grade,subject,title",(grade or "",grade or "",subject or "",subject or "",lang)).fetchall(); c.close()
    return render_template("textbooks.html",rows=rows,subjects=SUBJECTS,grade=grade or "",subject=subject or "",language=lang)
@app.route("/feedback",methods=["POST"])
def feedback():
    c=db(); c.execute("INSERT INTO feedback(name,email,category,message) VALUES(?,?,?,?)",(request.form.get("name",""),request.form.get("email",""),request.form.get("category","Ұсыныс"),request.form.get("message",""))); c.commit(); c.close()
    flash("Кері байланысыңыз қабылданды. Рақмет!","success"); return redirect(request.referrer or url_for("home"))
@app.route("/ai-status")
@login_required
@role_required("teacher","admin")
def ai_status():
    return jsonify(connected=bool(os.environ.get("ANTHROPIC_API_KEY")),provider="claude",model=os.environ.get("AI_MODEL", "claude-sonnet-5-5"))
@app.route("/health")
def health(): return jsonify(status="ok",product="IncluLearn AI",version="6.6")
@app.route("/assistant",methods=["GET","POST"])
@login_required
def assistant():
    answer=None
    if request.method=="POST":
        q=request.form.get("question","").strip()
        if q:
            try:
                answer=ai_generate("Сен IncluLearn AI платформасының қазақ тілінде жауап беретін білім беру көмекшісісің. Қысқа, нақты, жас ерекшелігіне сай жауап бер. Оқушының диагнозын анықтама және жеке дерек сұрама.",q,8000)
                c=db(); c.execute("INSERT INTO ai_chats(user_id,question,answer) VALUES(?,?,?)",(session["uid"],q,answer)); c.commit(); c.close()
            except Exception as e: flash("AI көмекші қатесі: "+str(e)[:180],"error")
    c=db(); history=c.execute("SELECT * FROM ai_chats WHERE user_id=? ORDER BY id DESC LIMIT 8",(session["uid"],)).fetchall(); c.close()
    return render_template("assistant.html",answer=answer,history=history)

@app.route("/assessment",methods=["GET","POST"])
@login_required
@role_required("teacher","admin")
def assessment():
    c=db()
    if request.method=="POST":
        title=request.form.get("title","").strip(); subject=request.form.get("subject",""); grade=int(request.form.get("grade",7)); criteria=request.form.get("criteria","").strip()
        if title and criteria:
            c.execute("INSERT INTO rubrics(teacher_id,title,subject,grade,criteria) VALUES(?,?,?,?,?)",(session["uid"],title,subject,grade,criteria)); c.commit(); flash("Бағалау критерийлері сақталды.","success")
        else: flash("Атауы мен критерийлерін толтырыңыз.","error")
    rubrics=c.execute("SELECT * FROM rubrics WHERE teacher_id=? ORDER BY id DESC",(session["uid"],)).fetchall(); c.close()
    return render_template("assessment.html",rubrics=rubrics,subjects=SUBJECTS)

@app.route("/assessment/analyze",methods=["POST"])
@login_required
@role_required("teacher","admin")
def assessment_analyze():
    answer=request.form.get("answer","").strip(); criteria=request.form.get("criteria","").strip()
    if not answer or not criteria: flash("Оқушы жауабы мен критерийлерді енгізіңіз.","error"); return redirect(url_for("assessment"))
    try:
        result=ai_generate("Сен критериалды бағалау бойынша әдіскерсің. Тек берілген критерийлерге сүйен. Әр критерий бойынша дәлел, орындалу деңгейі, ұсынылатын балл және жақсарту кері байланысын бер. Дәлелсіз баға қойма. Соңында мұғалім бекітуі қажет екенін жаз.",f"КРИТЕРИЙЛЕР:\n{criteria}\n\nОҚУШЫ ЖАУАБЫ:\n{answer}",12000)
        flash("AI талдауы дайын. Ұсынылған бағаны мұғалім өзі бекітеді.","success")
        return render_template("assessment.html",rubrics=[],subjects=SUBJECTS,analysis=result)
    except Exception as e: flash("Бағалау AI қатесі: "+str(e)[:180],"error"); return redirect(url_for("assessment"))

@app.route("/analytics")
@login_required
@role_required("teacher","admin")
def analytics():
    c=db(); uid=session["uid"]
    mats=c.execute("SELECT COUNT(*) n FROM materials WHERE teacher_id=?",(uid,)).fetchone()["n"]
    assigns=c.execute("SELECT COUNT(*) n FROM assignments WHERE teacher_id=?",(uid,)).fetchone()["n"]
    subs=c.execute("SELECT COUNT(*) n FROM submissions s JOIN assignments a ON a.id=s.assignment_id WHERE a.teacher_id=?",(uid,)).fetchone()["n"]
    reviewed=c.execute("SELECT COUNT(*) n FROM submissions s JOIN assignments a ON a.id=s.assignment_id WHERE a.teacher_id=? AND s.status='reviewed'",(uid,)).fetchone()["n"]
    c.close(); return render_template("analytics.html",mats=mats,assigns=assigns,subs=subs,reviewed=reviewed)

@app.route("/admin")
@login_required
@role_required("admin")
def admin():
    c=db(); users=c.execute("SELECT id,name,email,role FROM users ORDER BY id DESC").fetchall(); feedbacks=c.execute("SELECT * FROM feedback ORDER BY id DESC").fetchall(); c.close()
    return render_template("admin.html",users=users,feedbacks=feedbacks)
init_db()

if __name__=="__main__":
    app.run(host="127.0.0.1",port=int(os.environ.get("PORT",5002)),debug=False,use_reloader=False)
