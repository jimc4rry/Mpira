"""
Mpira MCP server - lets an AI assistant (Claude Desktop, Claude Code, ...)
read and write tickets on your Mpira workspace, with your own permissions.

Configuration (environment):
    MPIRA_URL      e.g. https://web-production-af909.up.railway.app
    MPIRA_API_KEY  a key created on your Profile page (mpk_...)

Every tool is a thin wrapper over the REST API under /api/v1/, so the server
can never do more than the key's owner could do in the browser.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("MPIRA_URL", "").rstrip("/")
API_KEY = os.environ.get("MPIRA_API_KEY", "")
TIMEOUT = 20
KEY_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9]{1,9})-(\d+)\s*$")

mcp = FastMCP("mpira")


class MpiraError(Exception):
    pass


def _api(method, path, query=None, body=None):
    if not BASE_URL or not API_KEY:
        raise MpiraError("Set MPIRA_URL and MPIRA_API_KEY in the MCP server configuration.")
    url = f"{BASE_URL}/api/v1/{path.lstrip('/')}"
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v not in (None, "")})
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {API_KEY}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode("utf-8")).get("error", {})
            message = err.get("message") or exc.reason
            details = err.get("details")
        except Exception:  # noqa: BLE001 - keep the HTTP status if the body isn't JSON
            message, details = exc.reason, None
        text = f"{exc.code}: {message}"
        if details:
            text += f" Details: {json.dumps(details, ensure_ascii=False)}"
        raise MpiraError(text) from None
    except urllib.error.URLError as exc:
        raise MpiraError(f"Cannot reach Mpira at {BASE_URL}: {exc.reason}") from None


def _split_key(key):
    m = KEY_RE.match(key or "")
    if not m:
        raise MpiraError(f"'{key}' is not an issue key. Use the form PROJECT-NUMBER, e.g. MPR-12.")
    return m.group(1).upper(), int(m.group(2))


def _run(fn):
    try:
        return json.dumps(fn(), ensure_ascii=False, indent=2)
    except MpiraError as exc:
        return f"Error: {exc}"


def _brief(issue):
    return {
        "key": issue.get("key"),
        "title": issue.get("title"),
        "type": issue.get("issue_type"),
        "status": issue.get("status_name") or issue.get("status"),
        "priority": issue.get("priority"),
        "assignee": issue.get("assignee_name"),
        "project": issue.get("project"),
        "story_points": issue.get("story_points"),
        "due_date": issue.get("due_date"),
    }


@mcp.tool()
def whoami() -> str:
    """Show which Mpira user this server is acting as."""
    return _run(lambda: _api("GET", "me/"))


@mcp.tool()
def list_projects() -> str:
    """List the projects you can access, with their keys (e.g. MPR)."""
    def fn():
        data = _api("GET", "projects/")
        rows = data.get("results", data) if isinstance(data, dict) else data
        return [{"key": p["key"], "name": p["name"]} for p in rows]
    return _run(fn)


@mcp.tool()
def my_issues(open_only: bool = True, limit: int = 50) -> str:
    """List issues assigned to you across all your projects."""
    def fn():
        data = _api("GET", "issues/", {"assignee": "me", "open": "true" if open_only else None})
        return [_brief(i) for i in data.get("results", [])[:limit]]
    return _run(fn)


@mcp.tool()
def search_issues(query: str = "", project: str = "", status: str = "", open_only: bool = True, limit: int = 50) -> str:
    """
    Search issues by text across your projects. Optionally limit to a project
    key (e.g. MPR) or to a status key (e.g. in_progress).
    """
    def fn():
        data = _api(
            "GET",
            "issues/",
            {"q": query, "project": project.upper() or None, "status": status or None, "open": "true" if open_only else None},
        )
        return [_brief(i) for i in data.get("results", [])[:limit]]
    return _run(fn)


@mcp.tool()
def get_issue(key: str) -> str:
    """Get the full details of an issue, e.g. MPR-12 (description, links, sprint, custom fields)."""
    def fn():
        project, number = _split_key(key)
        return _api("GET", f"projects/{project}/issues/{number}/")
    return _run(fn)


@mcp.tool()
def list_comments(key: str) -> str:
    """List the comments on an issue, oldest first."""
    def fn():
        project, number = _split_key(key)
        data = _api("GET", f"projects/{project}/issues/{number}/comments/")
        rows = data.get("results", data) if isinstance(data, dict) else data
        return [{"author": (c.get("author") or {}).get("display_name"), "created_at": c.get("created_at"), "body": c.get("body")} for c in rows]
    return _run(fn)


@mcp.tool()
def create_issue(
    project: str,
    title: str,
    issue_type: str = "task",
    description: str = "",
    priority: str = "medium",
    assignee: str = "",
    epic: str = "",
    parent: str = "",
    story_points: int | None = None,
    due_date: str = "",
) -> str:
    """
    Create an issue in a project. issue_type: epic, story, task, bug, subtask or test.
    priority: highest, high, medium, low or lowest. assignee: email or handle of a member.
    epic / parent: issue keys such as MPR-1. due_date: YYYY-MM-DD.
    """
    def fn():
        body = {
            "issue_type": issue_type,
            "title": title,
            "description": description,
            "priority": priority,
            "assignee": None,
            "epic": epic or None,
            "parent": parent or None,
            "story_points": story_points,
            "due_date": due_date or None,
        }
        if assignee:
            body["assignee"] = _member_id(project, assignee)
        return _brief(_api("POST", f"projects/{project.upper()}/issues/", body=body))
    return _run(fn)


@mcp.tool()
def update_issue(key: str, title: str = "", description: str = "", priority: str = "", assignee: str = "", story_points: int | None = None, due_date: str = "") -> str:
    """Change fields of an issue. Only the fields you pass are changed. Use transition_issue to change status."""
    def fn():
        project, number = _split_key(key)
        body = {}
        if title:
            body["title"] = title
        if description:
            body["description"] = description
        if priority:
            body["priority"] = priority
        if assignee:
            body["assignee"] = _member_id(project, assignee)
        if story_points is not None:
            body["story_points"] = story_points
        if due_date:
            body["due_date"] = due_date
        if not body:
            raise MpiraError("Nothing to change - pass at least one field.")
        return _brief(_api("PATCH", f"projects/{project}/issues/{number}/", body=body))
    return _run(fn)


@mcp.tool()
def transition_issue(key: str, status: str) -> str:
    """
    Move an issue to another status, e.g. in_progress or done. The project's
    workflow applies; if a move isn't allowed the error lists the reason.
    """
    def fn():
        project, number = _split_key(key)
        return _brief(_api("POST", f"projects/{project}/issues/{number}/transition/", body={"status": status}))
    return _run(fn)


@mcp.tool()
def add_comment(key: str, body: str) -> str:
    """Add a comment to an issue. Mention people with @handle."""
    def fn():
        project, number = _split_key(key)
        created = _api("POST", f"projects/{project}/issues/{number}/comments/", body={"body": body})
        return {"key": key, "author": (created.get("author") or {}).get("display_name"), "created_at": created.get("created_at")}
    return _run(fn)


def _member_id(project, who):
    """Resolve an email or handle to a user id, using the project's members."""
    data = _api("GET", f"projects/{project.upper()}/")
    members = data.get("members") or []
    for m in members:
        if who.lower() in (m.get("email", "").lower(), m.get("username", "").lower()):
            return m["id"]
    raise MpiraError(f"'{who}' is not a member of {project.upper()}.")


if __name__ == "__main__":
    mcp.run()
