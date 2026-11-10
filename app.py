import os, sqlite3, secrets, re, shutil, subprocess, tempfile
import markdown
import bleach
from markupsafe import Markup
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
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

def render_markdown(value):
    html = markdown.markdown(
        value or "",
        extensions=["extra", "sane_lists"]
    )
    allowed_tags = {
        "p", "h1", "h2", "h3", "h4",
        "strong", "em", "ul", "ol", "li",
        "blockquote", "code", "pre",
        "table", "thead", "tbody", "tr", "th", "td",
        "hr", "br"
    }
    clean_html = bleach.clean(
        html,
        tags=allowed_tags,
        attributes={},
        strip=True
    )
    return Markup(clean_html)

app.jinja_env.filters["render_markdown"] = render_markdown

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
        materials=c.execute("SELECT * FROM materials WHERE teacher_id=? ORDER BY id DESC",(session["uid"],)).fetchall()
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
        max_tokens=3000,
        system=system_prompt,
        messages=[{"role":"user", "content":user_prompt[:max_chars]}]
    )
    result="\n".join(block.text for block in response.content if getattr(block, "type", None)=="text").strip()
    if len(result)<120:
        raise RuntimeError("Claude жауабы тым қысқа немесе бос")
    return result

def adapt_text(text, support, grade, subject="", topic=""):
    if not text or len(text.strip()) < 30:
        raise ValueError("Материал тым қысқа. Кемінде 30 таңба енгізіңіз")

    selected = [x.strip() for x in support.split(",") if x.strip()]

    support_instructions = {
        "Оқуды түсіну және мәтінді жеңілдету": "Мәтінді қарапайым қазақ тілімен, қысқа сөйлемдермен қайта түсіндір.",
        "Қысқа қадамдарға бөлу": "Тақырыпты ретімен, нөмірленген нақты қадамдармен түсіндір.",
        "Қосымша мысалдар": "Тақырыпқа сәйкес кемінде екі дұрыс, түсінікті мысал келтір.",
        "Визуалды тірек": "Ұғымдардың байланысын мәтіндік схема немесе қарапайым сызба түрінде көрсет.",
        "Аудио нұсқа": "Оқуға ыңғайлы, табиғи айтылатын қысқа сөйлемдермен жеке мәтін дайында.",
        "Көру қолдауы": "Мәтінді анық тақырыпшалармен, қысқа абзацтармен және оқуға ыңғайлы форматта бер.",
        "Қысқаша резюме": "Тақырыптың ең маңызды ойларын қысқа қорытындыла.",
        "Қосымша күрделі тапсырмалар": "Оқушы деңгейіне сай үш бейімделген тапсырма құрастыр: жеңіл, орташа және күрделі. Әрқайсысының шарты мен орындау нұсқаулығын бер."
    }

    requested = "\\n".join(
        f"- {name}: {support_instructions.get(name, 'Осы қолдау түрін орында.')}"
        for name in selected
    ) or "- Қысқа абзацтар мен түсінікті тіл қолдан."

    instructions = f"""
Сен Қазақстан мектебіне арналған тәжірибелі инклюзивті педагогсің.
Сынып: {grade}. Пән: {subject}. Тақырып: {topic or 'бастапқы мәтіннен анықта'}.

МІНДЕТ:
Бастапқы материалды оқушының жасына сай бейімде.
Пәндік ақпаратты, терминдерді, формулаларды және кодты бұрмалама.
Тек бастапқы мәтіндегі ақпаратты пайдалан. Жоқ деректі ойдан қоспа.
Қазақ тілінде сауатты әрі ықшам жаз.

МІНДЕТТІ ЖАЛПЫ БӨЛІМДЕР:
## Тақырып
## Оқу мақсаты
## Негізгі ұғымдар
## Түсіндіру

ТАҢДАЛҒАН ҚОЛДАУ ТҮРЛЕРІ:
{requested}

ӨТЕ МАҢЫЗДЫ:
Жоғарыда таңдалған ӘРБІР қолдау түрін жеке тақырыпша ретінде орында.
Бірде-бір таңдалған қолдауды өткізіп алма.
Таңдалмаған қолдау түрлерін қоспа.
"Қосымша күрделі тапсырмалар" таңдалса ғана тапсырмалар жаса.
Егер ол таңдалмаса, тапсырмалар мен тесттер қоспа.
Критериалды бағалау бөлімін қоспа.
Кесте, сәндік символдар және көлденең сызықтар қолданба.
Markdown тақырыпшалары мен қалың қаріпті қолдануға болады.
Бір ойды қайталама. Қысқа абзацтар жаз.
"""

    result = ai_generate(
        instructions,
        "БАСТАПҚЫ ОҚУ МАТЕРИАЛЫ:\\n" + text,
        18000
    )

    if len(result) < 120 or result.strip() == text.strip():
        raise RuntimeError("AI жауабы тым қысқа немесе бастапқы мәтін өзгертілмеген")

    return result

@app.route("/material/<int:mid>")
@login_required
def material(mid):
    c=db(); m=c.execute("SELECT * FROM materials WHERE id=?",(mid,)).fetchone(); c.close()
    if not m: return "Материал табылмады",404
    if session.get("role") not in ("admin",) and session.get("role")!="student" and m["teacher_id"]!=session.get("uid"): return "Қолжетімділік жоқ",403
    return render_template("material.html",m=m)
@app.route("/material/<int:mid>/download/pdf")
@login_required
def download_material_pdf(mid):
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from xml.sax.saxutils import escape

    c = db()
    m = c.execute("SELECT * FROM materials WHERE id=?", (mid,)).fetchone()
    c.close()
    if not m:
        return "Материал табылмады", 404
    if session.get("role") != "admin" and session.get("role") != "student" and m["teacher_id"] != session.get("uid"):
        return "Қолжетімділік жоқ", 403

    font_path = os.path.join(ROOT, "static", "fonts", "Verdana.ttf")
    if "IncluVerdana" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("IncluVerdana", font_path))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm)
    styles = getSampleStyleSheet()
    heading = ParagraphStyle("MaterialTitle", parent=styles["Heading1"], fontName="IncluVerdana", fontSize=16, leading=21, spaceAfter=12)
    body = ParagraphStyle("MaterialBody", parent=styles["BodyText"], fontName="IncluVerdana", fontSize=9.5, leading=14, spaceAfter=7)
    story = [Paragraph(escape(m["title"]), heading),
             Paragraph(escape(f'{m["grade"]}-сынып · {m["subject"]} · {m["topic"]}'), body),
             Spacer(1, 10)]
    for line in (m["adapted"] or "").splitlines():
        line = line.strip()
        if line.startswith("#"):
            story.append(Paragraph(escape(line.lstrip("# ").strip()), heading))
        elif line:
            story.append(Paragraph(escape(line), body))
        else:
            story.append(Spacer(1, 4))
    doc.build(story)
    buffer.seek(0)
    return Response(buffer.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="material.pdf"'})


@app.route("/material/<int:mid>/download/docx")
@login_required
def download_material_docx(mid):
    import io
    from docx import Document
    from docx.shared import Pt

    c = db()
    m = c.execute("SELECT * FROM materials WHERE id=?", (mid,)).fetchone()
    c.close()
    if not m:
        return "Материал табылмады", 404
    if session.get("role") != "admin" and session.get("role") != "student" and m["teacher_id"] != session.get("uid"):
        return "Қолжетімділік жоқ", 403

    document = Document()
    document.add_heading(m["title"], 0)
    info = document.add_paragraph()
    info.add_run(f'{m["grade"]}-сынып · {m["subject"]} · {m["topic"]}')
    document.add_paragraph("")
    for line in (m["adapted"] or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("### "):
            document.add_heading(line[4:], level=3)
        elif line.startswith("## "):
            document.add_heading(line[3:], level=2)
        elif line.startswith("# "):
            document.add_heading(line[2:], level=1)
        else:
            document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return Response(buffer.getvalue(),
                    mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": 'attachment; filename="material.docx"'})


@app.route("/assign/<int:mid>",methods=["POST"])
@login_required
@role_required("teacher","admin")
def assign(mid):
    c = db()
    material = c.execute(
        "SELECT * FROM materials WHERE id=?", (mid,)
    ).fetchone()

    if not material:
        c.close()
        return "Материал табылмады", 404

    if session["role"] != "admin" and material["teacher_id"] != session["uid"]:
        c.close()
        return "Бұл материалды жариялауға рұқсатыңыз жоқ", 403

    c.execute(
        "INSERT INTO assignments(material_id,teacher_id,class_name,criteria) VALUES(?,?,?,?)",
        (mid, session["uid"], request.form.get("class_name", "").strip(),
         request.form.get("criteria", "").strip())
    )
    c.commit()
    c.close()

    flash("Материал тапсырма ретінде жарияланды.", "success")
    return redirect(url_for("dashboard"))


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


@app.route("/ai-tools")
@login_required
@role_required("teacher", "admin")
def ai_tools():
    return render_template("ai_tools.html")


def generate_tool_result(tool, title, grade, subject, topic, details):
    prompts = {
        "worksheet": (
            "Сен тәжірибелі мұғалімсің. Қазақ тілінде оқу мақсатына сай жұмыс парағын жаса. "
            "Тапсырмалар түсінікті, әртүрлі және оқушы жасына сәйкес болсын. "
            "Соңында жауап кілтін және бағалау критерийлерін бер."
        ),
        "visual": (
            "Сен визуалды оқыту маманысың. Тақырыпты қазақ тілінде қарапайым қадамдармен түсіндір. "
            "Негізгі ұғымдарды, олардың байланысын, мәтіндік сызбаны, мысалдарды және қысқаша қорытындыны бер. "
            "Сызбаны Markdown code block ішінде көрсет."
        ),
        "levels": (
            "Сен инклюзивті білім беру маманысың. Бір оқу мақсатын сақтап, бір сабақты үш деңгейге бейімде. "
            "1-деңгей: жеңіл мәтін, қысқа сөйлемдер, нақты қадамдар және визуалды тірек. "
            "2-деңгей: стандартты түсіндіру, мысалдар және жаттығулар. "
            "3-деңгей: күрделі тапсырмалар, логикалық сұрақтар және зерттеу жұмысы. "
            "Әр деңгейде бірдей оқу мақсаты сақталсын."
        )
    }
    user_prompt = (
        f"Құрал: {tool}\nТақырып: {title}\nСынып: {grade}\n"
        f"Пән: {subject}\nОқу тақырыбы: {topic}\nҚосымша талаптар: {details}"
    )
    return ai_generate(prompts[tool], user_prompt)


def save_ai_material(title, grade, subject, topic, content, tool_name):
    c = db()
    cur = c.execute(
        """INSERT INTO materials
        (teacher_id, title, grade, subject, topic, original, adapted, support)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (session["uid"], title, grade, subject, topic, topic, content, tool_name)
    )
    mid = cur.lastrowid
    c.commit()
    c.close()
    return mid


@app.route("/ai-tools/worksheet", methods=["GET", "POST"])
@login_required
@role_required("teacher", "admin")
def worksheet():
    result = None
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        grade = request.form.get("grade", "7")
        subject = request.form.get("subject", "Информатика")
        topic = request.form.get("topic", "").strip()
        details = (
            f"Тапсырма саны: {request.form.get('count', '5')}. "
            f"Қиындық деңгейі: {request.form.get('difficulty', 'Орташа')}. "
            f"Жауап кілті: {request.form.get('answers', 'yes')}."
        )
        if not title or not topic:
            flash("Тақырып пен оқу мақсатын немесе тақырып сипаттамасын енгізіңіз.", "error")
        else:
            try:
                result = generate_tool_result("worksheet", title, grade, subject, topic, details)
                mid = save_ai_material(title, grade, subject, topic, result, "AI жұмыс парағы")
                return redirect(url_for("material", mid=mid))
            except Exception as e:
                app.logger.exception("Worksheet generation failed")
                flash("Жұмыс парағын жасау қатесі: " + str(e)[:180], "error")
    return render_template("ai_tool_form.html", tool="worksheet", result=result, subjects=SUBJECTS)


@app.route("/ai-tools/visual", methods=["GET", "POST"])
@login_required
@role_required("teacher", "admin")
def visual_learning():
    result = None
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        grade = request.form.get("grade", "7")
        subject = request.form.get("subject", "Информатика")
        topic = request.form.get("topic", "").strip()
        if not title or not topic:
            flash("Тақырып пен түсіндіру мақсатын енгізіңіз.", "error")
        else:
            try:
                result = generate_tool_result("visual", title, grade, subject, topic, "Түсіндіруді кезеңдерге бөліп, сызба мен мысал қос.")
                mid = save_ai_material(title, grade, subject, topic, result, "Визуалды түсіндіру")
                return redirect(url_for("material", mid=mid))
            except Exception as e:
                app.logger.exception("Visual learning generation failed")
                flash("Түсіндіруді жасау қатесі: " + str(e)[:180], "error")
    return render_template("ai_tool_form.html", tool="visual", result=result, subjects=SUBJECTS)


@app.route("/ai-tools/levels", methods=["GET", "POST"])
@login_required
@role_required("teacher", "admin")
def learner_levels():
    result = None
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        grade = request.form.get("grade", "7")
        subject = request.form.get("subject", "Информатика")
        topic = request.form.get("topic", "").strip()
        if not title or not topic:
            flash("Сабақ тақырыбы мен оқу мақсатын енгізіңіз.", "error")
        else:
            try:
                result = generate_tool_result("levels", title, grade, subject, topic, "Үш деңгейдің тапсырмаларын, қолдау тәсілдерін және күтілетін нәтижелерін көрсет.")
                mid = save_ai_material(title, grade, subject, topic, result, "Үш деңгейлі тапсырмалар")
                return redirect(url_for("material", mid=mid))
            except Exception as e:
                app.logger.exception("Learner levels generation failed")
                flash("Үш деңгейлі сабақ жасау қатесі: " + str(e)[:180], "error")
    return render_template("ai_tool_form.html", tool="levels", result=result, subjects=SUBJECTS)


@app.route("/ai-tools/worksheet/pdf", methods=["POST"])
@login_required
@role_required("teacher", "admin")
def worksheet_pdf():
    content = request.form.get("content", "").strip()
    title = request.form.get("title", "Жұмыс парағы").strip()[:120]
    if not content:
        flash("PDF жасау үшін жұмыс парағының мәтіні жоқ.", "error")
        return redirect(url_for("worksheet"))
    try:
        import io
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted
        from xml.sax.saxutils import escape

        font_path = os.path.join(ROOT, "static", "fonts", "Verdana.ttf")
        if not os.path.exists(font_path):
            raise FileNotFoundError("Қазақша қаріп табылмады.")
        if "IncluVerdana" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("IncluVerdana", font_path))

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm)
        styles = getSampleStyleSheet()
        heading = ParagraphStyle("IncluHeading", parent=styles["Heading1"], fontName="IncluVerdana", fontSize=16, leading=21, spaceAfter=12)
        body = ParagraphStyle("IncluBody", parent=styles["BodyText"], fontName="IncluVerdana", fontSize=9.5, leading=14, spaceAfter=7)
        story = [Paragraph(escape(title), heading)]
        for line in content.splitlines():
            line = line.strip()
            if not line:
                story.append(Spacer(1, 4))
            elif line.startswith("#"):
                story.append(Paragraph(escape(line.lstrip("# ").strip()), heading))
            else:
                story.append(Paragraph(escape(line).replace("  ", "&nbsp;&nbsp;"), body))
        doc.build(story)
        buffer.seek(0)
        return Response(buffer.getvalue(), mimetype="application/pdf", headers={"Content-Disposition": 'attachment; filename="worksheet.pdf"'})
    except Exception as e:
        app.logger.exception("Worksheet PDF failed")
        flash("PDF жасау қатесі: " + str(e)[:180], "error")
        return redirect(url_for("worksheet"))


@app.route("/tts", methods=["POST"])
def text_to_speech():
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()

    if not text:
        return jsonify({"error": "Мәтін бос."}), 400
    if len(text) > 5000:
        return jsonify({"error": "Мәтін тым ұзын."}), 400

    piper = shutil.which("piper")
    model = os.path.join(ROOT, "kk_KZ-issai-high.onnx")

    if not piper or not os.path.exists(model):
        return jsonify({"error": "Қазақша дауыс моделі табылмады."}), 500

    text = re.sub(r"IncluLearn AI", "ИнклюЛёрн Эй-Ай", text, flags=re.I)
    text = re.sub(r"IncluLearn", "ИнклюЛёрн", text, flags=re.I)

    audio_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            audio_path = f.name

        result = subprocess.run(
            [piper, "-m", model, "-f", audio_path],
            input=text,
            text=True,
            capture_output=True,
            timeout=180,
            cwd=ROOT
        )

        if result.returncode != 0:
            return jsonify({"error": "Дыбыстау қатесі: " + result.stderr[:300]}), 500

        with open(audio_path, "rb") as f:
            audio = f.read()

        return Response(audio, mimetype="audio/wav")

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Дыбыстауға берілген уақыт аяқталды."}), 504
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 500
    finally:
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)


init_db()

if __name__=="__main__":
    app.run(host="127.0.0.1",port=int(os.environ.get("PORT",5002)),debug=False,use_reloader=False)
