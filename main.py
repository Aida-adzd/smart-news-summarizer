import os
import json
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is not set in .env")
if not NEWS_API_KEY:
    raise ValueError("NEWS_API_KEY is not set in .env")

client = OpenAI(api_key=OPENAI_API_KEY)
NEWS_API_URL = "https://newsapi.org/v2/everything"

app = FastAPI(title="Smart News Summarizer")

class ChatRequest(BaseModel):
    message: str

with open("system_prompt.txt", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

@app.post("/smart-news")
def smart_news(req: ChatRequest):
    user_message = req.message
    final_output = ""

    try:
        analysis_resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ]
        )

        topics_count_text = analysis_resp.choices[0].message.content.strip()
        topics_count_text = topics_count_text[topics_count_text.find("{"):topics_count_text.rfind("}")+1]
        topics_count = json.loads(topics_count_text)

    except Exception as e:
        print("Topic extraction error:", e)
        topics_count = {"technology": 5}  # fallback

    for topic_index, (topic, count) in enumerate(topics_count.items(), start=1):
        final_output += f"=== Topic {topic_index}: {topic.upper()} ({count} news) ===\n\n"

        try:
            response = requests.get(
                NEWS_API_URL,
                params={"q": topic, "apiKey": NEWS_API_KEY, "pageSize": count, "language": "en"},
                timeout=10
            )
            response.raise_for_status()
            articles = response.json().get("articles", [])
        except requests.exceptions.Timeout:
            final_output += f"Timeout while fetching news for '{topic}'\n\n"
            continue
        except Exception as e:
            final_output += f"Failed to fetch news for '{topic}': {e}\n\n"
            continue

        if not articles:
            final_output += "No news found.\n\n"
            continue

        news_list_text = "\n\n".join(
            f"Title: {art['title']}\nContent: {art.get('content', '')}\nLink: {art.get('url', '')}"
            for art in articles
        )

        try:
            # در بخش خلاصه‌سازی به جای فرمت ساده:
            summary_resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant. Summarize each news item in 2-3 sentences. Format result in Markdown as:\n\n## Title\n**Summary:** ...\n[Read More](link)\n---\n"
                    },
                    {"role": "user", "content": news_list_text}
                ]
            )
            summaries_text = summary_resp.choices[0].message.content.strip()

        except Exception as e:
            summaries_text = f"Failed to summarize: {e}"

        final_output += summaries_text + "\n\n"

    return {"news_text": final_output}
