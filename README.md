# Essay Pilot

Essay Pilot - Telegram ichidan ishlaydigan, insho tekshiruvchi MVP.

Loyiha foydalanuvchi uchun qulay oqim bilan qurilgan:

- Matn yozish yoki rasm yuklash
- Telegram botga to'g'ridan-to'g'ri matn yoki rasm yuborib tekshirtirish
- Limitni avtomatik tekshirish
- Tekshirilayotgan holatni ko'rsatish
- Natijada ball, daraja, xatolar va tavsiyalarni chiqarish
- History bo'limida avvalgi yuborilgan insholarni ko'rish

## Baholash tizimi

- O'zbekcha insholar: 75 ballik tizim, 12 ta mezon.
- Inglizcha insholar: IELTS Writing Task 2 mezonlari bo'yicha 0-9 band.

O'zbekcha 12 mezon:

1. Mavzuni yoritish
2. Tezis va pozitsiya
3. Dalil va misollar
4. Mantiqiy izchillik
5. Kompozitsiya
6. Uslub va registr
7. Lug'at boyligi
8. Grammatika
9. Imlo
10. Punktuatsiya
11. Xulosa
12. Hajm va talabga moslik

Inglizcha IELTS mezonlari:

1. Task Response
2. Coherence and Cohesion
3. Lexical Resource
4. Grammatical Range and Accuracy

## OCR strategiyasi

Default tavsiya etilgan local OCR:

- `OCR_PROVIDER=paddleocr`
- birinchi ishga tushganda PaddleOCR model fayllarini yuklab oladi
- internet bo'lmasa yoki import xato bersa, tizim fallback provider'larni sinab ko'radi

Qo'llab-quvvatlanadigan provider'lar:

- `paddleocr`
- `gemini`
- `tesseract`
- `auto`

## Nega bu arxitektura qulay

Matn va rasm ikkalasi ham bitta pipeline orqali o'tadi:

1. Submission yaratiladi
2. Limit kamaytiriladi
3. Background processing boshlanadi
4. Agar rasm bo'lsa OCR qilinadi
5. Matn tozalanadi
6. AI yoki demo evaluator tahlil qiladi
7. Frontend polling orqali natijani olib turadi

Bu usul foydalanuvchi uchun "osilib qoldi" degan hissni kamaytiradi va keyinchalik haqiqiy OCR/AI servislarni bemalol ulash imkonini beradi.

## Tuzilma

```text
app/
  main.py
  config.py
  db.py
  schemas.py
  storage.py
  routes/api.py
  services/analysis.py
  services/ocr.py
bot/
  main.py
frontend/
  index.html
  style.css
  app.js
```

## O'rnatish

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

`PaddleOCR` uchun odatda alohida `pip install paddlepaddle paddleocr` qilish shart emas, chunki ular `requirements.txt` ichida bor.

## Backendni ishga tushirish

```bash
uvicorn app.main:app --reload
```

Keyin brauzerda:

```text
http://localhost:8000
```

## Telegram botni ishga tushirish

`.env` ichida `TELEGRAM_BOT_TOKEN` va `APP_URL` ni to'ldiring.

```bash
python -m bot.main
```

Bot `/start` da WebApp tugmasini yuboradi.

## Haqiqiy servislarni ulash

### OCR

- tavsiya etilgan default: `PaddleOCR`
- `.env` ichida `OCR_PROVIDER=paddleocr` bo'lsa, lokal OCR ishlaydi
- birinchi run paytida model fayllari avtomatik yuklanadi
- `GEMINI_API_KEY` bo'lsa, `OCR_PROVIDER=gemini` orqali Gemini Vision ishlaydi
- `tesseract` ham fallback sifatida qoldirilgan

### AI

- `OPENAI_API_KEY` bo'lsa, OpenAI orqali JSON natija olishga harakat qiladi
- xatolik bo'lsa yoki kalit bo'lmasa, demo evaluator ishlaydi

## Telegram WebApp xavfsizligi

Frontend Telegram ichida ochilganda `initData` ni backendga yuboradi. Backend shu imzoni
`TELEGRAM_BOT_TOKEN` orqali tekshiradi va so'rovdagi `telegram_id` aynan shu
foydalanuvchiga tegishli ekanini tasdiqlaydi.

Mahalliy brauzer demo rejimi kerak bo'lsa, `.env` ichida vaqtincha quyidagini yoqing:

```text
ALLOW_DEMO_AUTH=true
```

Production uchun `ALLOW_DEMO_AUTH=false` qoldiring.

## Admin sozlamalari

Bot orqali admin bo'lish:

```text
/setadminme <ADMIN_SECRET>
```

Yoki `.env` ichida:

```text
ADMIN_TELEGRAM_IDS=123456789
```

## Admin endpoint

Manual to'lovni tasdiqlash uchun:

`POST /api/payments/confirm`

Header:

```text
x-admin-secret: <ADMIN_SECRET>
```

Body:

```json
{
  "telegram_id": "12345",
  "limits": 10,
  "note": "Click to'lov"
}
```

## E'tibor

- Demo evaluator mahsulot oqimini ko'rsatish uchun bor
- Production rejimida prompt, rubrika va moderation qat'iylashtirilishi kerak
- Qo'lda yozilgan matn uchun OCR har doim ham 100% aniq bo'lmaydi
- PaddleOCR birinchi ishga tushganda model yuklab olgani uchun birinchi OCR seansi sekinroq bo'lishi mumkin
- Render Free web service lokal SQLite bazasi va upload fayllarni redeploy, restart yoki
  spin-down paytida yo'qotishi mumkin. Production uchun paid persistent disk yoki tashqi
  database/storage ishlating.
