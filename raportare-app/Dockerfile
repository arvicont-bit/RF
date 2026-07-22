FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV APP_SECRET_KEY=schimba-aceasta-valoare-in-productie
EXPOSE 5050

CMD ["sh", "-c", "python3 app/seed_chart_accounts.py; gunicorn -w 4 -b 0.0.0.0:5050 main:app"]
