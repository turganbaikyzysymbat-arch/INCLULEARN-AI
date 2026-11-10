# IncluLearn AI 6.6 — Claude-only

Бұл нұсқа Anthropic Claude API-мен ғана жұмыс істейді. Басқа провайдерлер мен олардың API кілттері алынып тасталды. Claude сұранысында қолдау көрсетілмейтін `temperature` параметрі қолданылмайды. API қатесі болса, жалған демо-материал сақталмайды: нақты қате көрсетіледі.

## macOS орнату
```bash
cd ~/Downloads/IncluLearn_AI_6.6_Claude_Final
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
nano .env
```
`.env` ішіне өзіңіздің Anthropic API кілтіңізді енгізіңіз:
```env
ANTHROPIC_API_KEY=өз_Claude_API_кілт
AI_MODEL=claude-sonnet-5-5
```
Кілтті ешкімге жібермеңіз. `.env` ZIP архивіне қосылмайды.

## Іске қосу
```bash
python3 -c "import app; app.app.run(host='127.0.0.1', port=8000, debug=False, use_reloader=False)"
```
Браузер: http://127.0.0.1:8000
Егер порт бос болмаса, 8001 немесе 8002 қолданыңыз.

Демо әкімші: `admin@inclulearn.local` / `Admin123!`. Алғашқы кіргеннен кейін құпиясөзді ауыстырыңыз.

## Маңызды
Материал Claude API арқылы жасалады. Сапаны мұғалім соңғы рет тексеруі керек. Бұл ортада браузерлік end-to-end тексеру жүргізілмеді; Python синтаксисі, негізгі Claude сұранысының параметрлері және ZIP құрылымы тексерілді.
