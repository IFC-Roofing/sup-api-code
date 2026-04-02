"""
Chat endpoint — Sup dashboard agent with IFC API tool use.
Can search projects, pull details, read conversations, check action trackers.
"""
import os
import json
import httpx
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse
from backend.auth import get_current_user

router = APIRouter()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"

IFC_API_BASE = os.getenv("IFC_API_BASE", "https://omni.ifc.shibui.ar")
IFC_API_TOKEN = os.getenv("IFC_API_TOKEN", "")

# Load knowledge base at startup
KB_PATH = Path(__file__).parent.parent / "knowledge-base.md"
KNOWLEDGE_BASE = ""
if KB_PATH.exists():
    KNOWLEDGE_BASE = KB_PATH.read_text()

SYSTEM_PROMPT = f"""You are Sup 🏗️ — the supplement AI for IFC Roofing, powering the executive dashboard chat.

## Vibe
- Practical, concise, helpful
- No fluff — get to the point
- Friendly but professional
- Keep responses SHORT — this is a chat widget, not an essay
- Use bullet points over paragraphs

## Tools
You have access to the IFC API to look up real project data. USE the tools when someone asks about a project, status, numbers, or anything that requires real data. Don't guess — look it up.

## Boundaries
- Read-only on all APIs — never claim to write or modify anything
- Don't share internal strategy or Alvaro's personal notes
- Sales reps and leadership have final authority

## Supplement Knowledge
{KNOWLEDGE_BASE}
"""

# Tool definitions for Anthropic API
TOOLS = [
    {
        "name": "search_projects",
        "description": "Search IFC projects by name, insured name, or address. Returns a list of matching projects with basic info (id, name, status, sales rep, RCV).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term — project name, insured name, or address"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_project",
        "description": "Get full details for a specific project by ID. Returns status, sales rep, RCV, dates, action trackers, and more.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "The project ID number"
                }
            },
            "required": ["project_id"]
        }
    },
    {
        "name": "get_project_posts",
        "description": "Get conversation posts/notes for a project. Includes @tags like @momentum, @ifc, @supplement, @client. Shows the communication history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "The project ID number"
                }
            },
            "required": ["project_id"]
        }
    },
    {
        "name": "get_pipeline_summary",
        "description": "Get a summary of all projects grouped by status. Shows how many jobs are in each pipeline stage and total RCV.",
        "input_schema": {
            "type": "object",
            "properties": {},
        }
    },
]


def ifc_headers():
    return {"Authorization": f"Bearer {IFC_API_TOKEN}"}


async def execute_tool(name: str, input_data: dict) -> str:
    """Execute a tool call and return the result as a string."""
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            if name == "search_projects":
                r = await client.get(
                    f"{IFC_API_BASE}/projects",
                    params={"search": input_data["query"]},
                    headers=ifc_headers()
                )
                r.raise_for_status()
                projects = r.json()
                if isinstance(projects, dict):
                    projects = projects.get("data", projects.get("projects", []))
                # Slim down response
                results = []
                for p in projects[:15]:
                    results.append({
                        "id": p.get("id"),
                        "name": p.get("name", p.get("insured_name", "")),
                        "status": p.get("status", ""),
                        "sales_rep": p.get("sales_rep", p.get("sales_rep_name", "")),
                        "rcv": p.get("collected_rcv") or p.get("rcv"),
                        "updated_at": p.get("updated_at", ""),
                    })
                return json.dumps(results, default=str)

            elif name == "get_project":
                r = await client.get(
                    f"{IFC_API_BASE}/projects/{input_data['project_id']}",
                    headers=ifc_headers()
                )
                r.raise_for_status()
                return json.dumps(r.json(), default=str)

            elif name == "get_project_posts":
                r = await client.get(
                    f"{IFC_API_BASE}/posts",
                    params={"project_id": input_data["project_id"]},
                    headers=ifc_headers()
                )
                r.raise_for_status()
                posts = r.json()
                if isinstance(posts, dict):
                    posts = posts.get("data", posts.get("post_notes", []))
                # Slim down
                results = []
                for p in posts[:30]:
                    results.append({
                        "id": p.get("id"),
                        "content": (p.get("content") or p.get("body", ""))[:500],
                        "user": p.get("user", p.get("author", "")),
                        "tags": p.get("tags", []),
                        "created_at": p.get("created_at", ""),
                    })
                return json.dumps(results, default=str)

            elif name == "get_pipeline_summary":
                r = await client.get(
                    f"{IFC_API_BASE}/projects",
                    params={"per_page": 1000},
                    headers=ifc_headers()
                )
                r.raise_for_status()
                projects = r.json()
                if isinstance(projects, dict):
                    projects = projects.get("data", projects.get("projects", []))

                summary = {}
                total_rcv = 0
                for p in projects:
                    status = p.get("status", "Unknown")
                    rcv = float(p.get("collected_rcv") or p.get("rcv") or 0)
                    if status not in summary:
                        summary[status] = {"count": 0, "rcv": 0}
                    summary[status]["count"] += 1
                    summary[status]["rcv"] += rcv
                    total_rcv += rcv

                return json.dumps({
                    "total_projects": len(projects),
                    "total_rcv": round(total_rcv, 2),
                    "by_status": summary,
                }, default=str)

            else:
                return json.dumps({"error": f"Unknown tool: {name}"})

        except httpx.HTTPStatusError as e:
            return json.dumps({"error": f"API error: {e.response.status_code}"})
        except Exception as e:
            return json.dumps({"error": str(e)})


# Per-user conversation history (in-memory)
conversations: dict[str, list] = {}
MAX_HISTORY = 30


@router.post("/api/chat")
async def chat(request: Request, user: dict = Depends(get_current_user)):
    """Chat with Sup — streaming, with IFC API tool use."""
    body = await request.json()
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Missing message")

    user_email = user.get("sub", "unknown")

    # Get or create conversation history
    if user_email not in conversations:
        conversations[user_email] = []
    history = conversations[user_email]

    # Add user message
    history.append({"role": "user", "content": message})

    # Trim history
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
        conversations[user_email] = history

    # Handle tool use loop (non-streaming for tool calls, streaming for final response)
    max_tool_rounds = 5
    for _ in range(max_tool_rounds):
        # Make non-streaming call to check for tool use
        async with httpx.AsyncClient(timeout=60) as client:
            payload = {
                "model": MODEL,
                "max_tokens": 2048,
                "system": SYSTEM_PROMPT,
                "messages": history,
                "tools": TOOLS,
            }
            headers = {
                "x-api-key": ANTHROPIC_API_KEY,
                "content-type": "application/json",
                "anthropic-version": "2023-06-01",
            }
            resp = await client.post(ANTHROPIC_URL, json=payload, headers=headers)
            resp.raise_for_status()
            result = resp.json()

        # Check if model wants to use tools
        if result.get("stop_reason") == "tool_use":
            # Process tool calls
            assistant_content = result.get("content", [])
            history.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for block in assistant_content:
                if block.get("type") == "tool_use":
                    tool_result = await execute_tool(block["name"], block["input"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": tool_result,
                    })

            history.append({"role": "user", "content": tool_results})
            continue  # Loop back for another round

        else:
            # Final response — extract text and stream it back
            text_content = ""
            for block in result.get("content", []):
                if block.get("type") == "text":
                    text_content += block.get("text", "")

            # Save to history
            history.append({"role": "assistant", "content": text_content})

            # Stream the final text back to frontend
            async def stream_text():
                # Send in chunks to simulate streaming feel
                chunk_size = 20
                for i in range(0, len(text_content), chunk_size):
                    chunk = text_content[i:i + chunk_size]
                    data = {"choices": [{"delta": {"content": chunk}, "index": 0}]}
                    yield f"data: {json.dumps(data)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(stream_text(), media_type="text/event-stream")

    # If we exceeded tool rounds, return what we have
    return StreamingResponse(
        iter(["data: {\"choices\":[{\"delta\":{\"content\":\"Sorry, I hit a complexity limit. Try a simpler question.\"},\"index\":0}]}\n\n", "data: [DONE]\n\n"]),
        media_type="text/event-stream"
    )
