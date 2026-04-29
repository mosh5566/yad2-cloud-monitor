# מוניטור יד 2 - גרסת ענן ☁️

עוקב אחר מודעות פריוס ב-yad2 ושולח WhatsApp **24/7 גם כשהמחשב כבוי**.

רץ על **GitHub Actions** - חינם לחלוטין, **ללא כרטיס אשראי**.

## ⚡ התקנה בלחיצה

פתח PowerShell בתיקייה הזו והרץ:

```powershell
.\setup.ps1
```

הסקריפט יעשה הכל אוטומטית:
1. יבקש להתחבר ל-GitHub (פעם אחת בדפדפן)
2. ייצור repo פרטי בשם `yad2-cloud-monitor`
3. יעלה את הקוד
4. יגדיר את הסודות (API_TOKEN, ID_INSTANCE, PHONE)
5. יפעיל את הריצה הראשונה

זה הכל. תוך 2-3 דקות תקבל WhatsApp "מערכת ענן פעילה".

## איך זה עובד?

- GitHub Actions מריץ את `monitor.py` **כל 10 דקות** אוטומטית
- כל ריצה: סורק את yad2, אם יש מודעה חדשה - שולח WhatsApp
- ה-watermark נשמר ב-`state.json` ועושה commit חזרה ל-repo
- הכל קורה בשרתים של GitHub - **המחשב שלך לא חייב להיות דולק**

## מבנה

```
מוניטור יד 2 ענן/
├── monitor.py             # הסקריפט הראשי
├── requirements.txt       # תלויות Python
├── state.json             # watermark מתעדכן אוטומטית
├── setup.ps1              # התקנה בלחיצה
├── .github/workflows/
│   └── check.yml          # GitHub Actions cron job
└── README.md
```

## ניטור ידני

```powershell
# פתיחת הריצות בדפדפן
gh repo view --web

# צפייה בלוג של הריצה האחרונה
gh run view --log

# הרצה ידנית מיידית
gh workflow run check.yml
```

## עצירה זמנית

ב-GitHub: Settings > Actions > "Disable Actions"

או הרצה: 
```powershell
gh workflow disable check.yml
```

להפעלה מחדש: 
```powershell
gh workflow enable check.yml
```

## מגבלות

- GitHub Actions cron מובטח לרוץ ב~10-15 דקות (לא תמיד בדיוק על השנייה).
- 2,000 דקות חינם לחודש (private repo). הסקריפט שלנו צורך ~30s לריצה = ~3,000 ריצות לחודש מספיקות בקלות.
- אם רוצים אפס מגבלה: להפוך את ה-repo לציבורי (Settings > Change visibility).
