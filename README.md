# TubeSplitter Telegram Bot

בוט טלגרם פשוט שמקבל קישור לפלייליסט מיוטיוב ומחזיר רשימה של כל הסרטונים בפורמט קריא.

## תכונות

- תמיכה בעברית ובאנגלית
- זיהוי כמה פלייליסטים באותה הודעה, לפי הסדר
- התעלמות מטקסט נוסף סביב הקישורים
- ולידציה לקישורים לא תקינים
- טיפול בסרטונים לא זמינים בלי לעצור את כל הפלייליסט
- פיצול אוטומטי של תגובות ארוכות לכמה הודעות

## דרישות

- Python 3.12+
- טוקן בוט מטלגרם במשתנה סביבה בשם `TELEGRAM_BOT_TOKEN`

## התקנה

### Linux / WSL

הרצה מומלצת:

```bash
chmod +x setup.sh run_bot.sh update_repo.sh
./setup.sh
```

אחרי זה תערוך את `.env` ותכניס טוקן אמיתי, ואז:

```bash
./run_bot.sh
```

לעדכון מהיר של הריפו על השרת, כשהבוט כבוי:

```bash
./update_repo.sh
```

הסקריפט מגבה קבצים ותיקיות שמוחרגים מ־git, מעדכן מה־GitHub, משחזר את הגיבוי, ומתקין מחדש תלויות רק אם `requirements.txt` השתנה בעדכון.

אם אתה מעדיף ידנית:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# ערוך את .env
python main.py
```

## שימוש

- `/start` מציג הסבר קצר וכפתורי שפה
- `/help` מציג מה הבוט יודע לעשות
- `/language` פותח בורר שפה

דוגמאות להודעות נתמכות:

```text
https://www.youtube.com/playlist?list=PL1234567890
```

```text
היי, תטפל בזה:
https://www.youtube.com/playlist?list=PL1234567890
וגם בזה:
https://www.youtube.com/watch?v=abc123&list=PL0987654321
```

## הערות

- הבוט כתוב בצורה שתתאים גם ללינוקס וגם ל-WSL.
- העדפת השפה נשמרת פר-משתמש באמצעות persistence מקומי.
- `run_bot.sh` טוען אוטומטית משתנים מתוך `.env`.
