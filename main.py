import os, json, logging, requests, smtplib
from typing import List, Dict, Any
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from fastapi import FastAPI, Request, HTTPException, Header
from pydantic import BaseModel, EmailStr, ValidationError
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.example.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
MCP_API_KEY = os.getenv("MCP_API_KEY")
NEWS_API_URL = "https://newsapi.org/v2/everything"

if not MCP_API_KEY:
    raise RuntimeError("MCP_API_KEY not set in .env")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
app = FastAPI(title="MCP Server for News Tools")
logger = logging.getLogger("uvicorn")

class FetchNewsParams(BaseModel):
    topic: str
    date: str
    count: int = 5

class SendEmailParams(BaseModel):
    to_email: EmailStr
    subject: str
    body: str

class SummarizeParams(BaseModel):
    articles: List[Dict[str, Any]]

class TopicCount(BaseModel):
    topic: str
    count: int = 5

class SmartNewsEmailParams(BaseModel):
    date: str
    email: EmailStr
    topics: List[TopicCount]

def fetch_news_impl(topic: str, date: str, count: int = 5):
    r = requests.get(
        NEWS_API_URL,
        params={"q": topic, "apiKey": NEWS_API_KEY, "pageSize": count, "language": "en", "from": date, "to": date},
        timeout=10,
    )
    r.raise_for_status()
    return r.json().get("articles", [])

def summarize_articles_impl(articles: List[Dict[str, Any]]) -> str:
    if not articles:
        return "<p>No news found for the selected topics/date.</p>"

    news_text = "\n\n".join(
        f"Title: {a.get('title')}\nDate: {a.get('publishedAt')}\nContent: {a.get('content')}\nLink: {a.get('url')}"
        for a in articles
    )

    if not client:
        return "OpenAI API key missing"

    prompt = [
        {"role": "system",
         "content": (
             "You are a helpful assistant. "
             "Summarize each news item in 2-3 sentences. "
             "Output clean HTML with this format:\n"
             "<h2>Title</h2>\n"
             "<p><b>Date:</b> YYYY-MM-DD</p>\n"
             "<p><b>Summary:</b> ...</p>\n"
             "<p><a href='link'>Read More</a></p>\n"
             "<hr>\n"
         )
        },
        {"role": "user", "content": news_text}
    ]

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=prompt
    )

    return resp.choices[0].message.content.strip()

def send_email_impl(to_email: str, subject: str, body: str):
    server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
    server.login(SMTP_USER, SMTP_PASS)
    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html"))
    server.sendmail(SMTP_USER, to_email, msg.as_string())
    server.quit()
    return {"sent": True}

def smart_news_email_impl(date: str, email: str, topics: List[Dict[str, Any]]):
    all_articles = []
    for t in topics:
        articles = fetch_news_impl(topic=t["topic"], date=date, count=t.get("count", 5))
        all_articles.extend(articles)

    summary_html = summarize_articles_impl(all_articles)

    filename = f"news_summary_{date}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(summary_html)

    send_email_impl(to_email=email, subject=f"Daily News Summary - {date}", body=summary_html)
    return {"status": "success", "file": filename}


TOOLS_IMPL = {
    "fetch_news": fetch_news_impl,
    "summarize_articles": summarize_articles_impl,
    "send_email": send_email_impl,
    "smart_news_email": smart_news_email_impl,
}

TOOLS_MODELS = {
    "fetch_news": FetchNewsParams,
    "summarize_articles": SummarizeParams,
    "send_email": SendEmailParams,
    "smart_news_email": SmartNewsEmailParams,
}

TOOLS_METADATA = {
    "fetch_news": {"name": "fetch_news", "description": "Fetch news articles", "params_schema": FetchNewsParams.schema()},
    "summarize_articles": {"name": "summarize_articles", "description": "Summarize articles with OpenAI", "params_schema": SummarizeParams.schema()},
    "send_email": {"name": "send_email", "description": "Send HTML email via SMTP", "params_schema": SendEmailParams.schema()},
    "smart_news_email": {"name": "smart_news_email", "description": "Fetch multiple topics, summarize, save HTML, and send email", "params_schema": SmartNewsEmailParams.schema()},
}

# ---------- Helper ----------
def check_api_key(x_mcp_api_key: str):
    if not x_mcp_api_key or x_mcp_api_key != MCP_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

# ---------- Endpoints ----------
@app.get("/mcp/registry")
async def get_registry(x_mcp_api_key: str = Header(None)):
    check_api_key(x_mcp_api_key)
    return {"tools": TOOLS_METADATA}

@app.post("/jsonrpc")
async def handle_jsonrpc(request: Request, x_mcp_api_key: str = Header(None)):
    check_api_key(x_mcp_api_key)
    payload = await request.json()
    req_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params", {})
    if not method or not method.startswith("tool."):
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}
    tool_name = method.split(".", 1)[1]
    if tool_name not in TOOLS_IMPL:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Tool not found"}}
    try:
        model = TOOLS_MODELS[tool_name](**params)
        result = TOOLS_IMPL[tool_name](**model.dict())
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    except ValidationError as e:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Invalid params", "data": json.loads(e.json())}}
    except Exception as e:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": "Server error", "data": str(e)}}
