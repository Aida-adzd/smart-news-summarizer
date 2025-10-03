import os, requests
from dotenv import load_dotenv

load_dotenv()
MCP_URL = "http://localhost:8000/jsonrpc"
MCP_KEY = os.getenv("MCP_API_KEY")
HEADERS = {"Content-Type": "application/json", "X-MCP-API-KEY": MCP_KEY}

def call_tool(method, params, req_id=1):
    payload = {"jsonrpc": "2.0", "id": req_id, "method": f"tool.{method}", "params": params}
    r = requests.post(MCP_URL, json=payload, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.json().get("result")

params = {
    "date": "2025-10-02",
    "email": "aida.adzd@gmail.com",
    "topics": [
        {"topic": "Sports", "count": 2},
        {"topic": "Crime", "count": 3}
    ]
}

result = call_tool("smart_news_email", params)
# print("HTML file saved as:", result["file"])
# print("Email sent successfully!")
