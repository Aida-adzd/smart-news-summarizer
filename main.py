import os
import json
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from fastapi import FastAPI
from pydantic import BaseModel, EmailStr
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not set in .env")
if not NEWS_API_KEY:
    raise ValueError("NEWS_API_KEY not set in .env")
if not SMTP_USER or not SMTP_PASS:
    raise ValueError("SMTP_USER or SMTP_PASS not set in .env")

client = OpenAI(api_key=OPENAI_API_KEY)
app = FastAPI(title="Smart News Summarizer with Email")
NEWS_API_URL = "https://newsapi.org/v2/everything"

class NewsRequest(BaseModel):
    topics: str         # comma-separated topics
    date: str           # YYYY-MM-DD format
    email: EmailStr     # destination email

def send_email(subject: str, body: str, to_email: str):
    server = smtplib.SMTP_SSL(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT")))
    server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
    msg = MIMEMultipart()
    msg["From"] = os.getenv("SMTP_USER")
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html"))
    server.sendmail(os.getenv("SMTP_USER"), to_email, msg.as_string())
    server.quit()

def fetch_news(topic: str, date: str, count: int):
    try:
        resp = requests.get(
            NEWS_API_URL,
            params={
                "q": topic,
                "apiKey": NEWS_API_KEY,
                "pageSize": count,
                "language": "en",
                "from": date,
                "to": date,
                "sortBy": "publishedAt"
            },
            timeout=10
        )
        resp.raise_for_status()
        return resp.json().get("articles", [])
    except requests.exceptions.Timeout:
        return []
    except Exception:
        return []

def summarize_articles(articles):
    news_list_text = "\n\n".join(
        f"Title: {art['title']}\nDate: {art.get('publishedAt','')}\nContent: {art.get('content', '')}\nLink: {art.get('url', '')}"
        for art in articles
    )

    if not news_list_text.strip():
        return "No news found for this topic/date."

    try:
        summary_resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content":
                        "You are a helpful assistant. "
                        "Summarize each news item in 2-3 sentences. "
                        "Format result in HTML as:\n"
                        "<h2>Title</h2>\n"
                        "<p><b>Date:</b> YYYY-MM-DD</p>\n"
                        "<p><b>Summary:</b> ...</p>\n"
                        "<p><a href='link'>Read More</a></p>\n<hr>\n"
                },
                {"role": "user", "content": news_list_text}
            ]
        )
        return summary_resp.choices[0].message.content.strip()
    except Exception as e:
        return f"Failed to summarize: {e}"

@app.post("/smart-news-email")
def smart_news_email(req: NewsRequest):
    topics_list = [t.strip() for t in req.topics.split(",") if t.strip()]
    date = req.date
    user_email = req.email

    email_body = f"<h1>Daily News Summary - {date}</h1>"
    all_summaries = ""

    for topic_index, topic in enumerate(topics_list, start=1):
        articles = fetch_news(topic, date, count=5)  # default 5 per topic
        summaries_html = summarize_articles(articles)
        all_summaries += f"<h2>Topic {topic_index}: {topic.title()}</h2>\n" + summaries_html + "\n"

    email_body += all_summaries

    send_email(subject=f"Daily News Summary - {date}", body=email_body, to_email=user_email)

    return {"status": "success", "message": f"News summary sent to {user_email}"}
