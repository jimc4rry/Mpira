# Mpira MCP server

Lets Claude (Claude Desktop, Claude Code, or any MCP client) read and write
tickets on your Mpira workspace. It uses **your** API key, so it can do
exactly what you can do in the browser - nothing more.

## 1. Create an API key

On Mpira, open **Profile** → **API keys** → enter a name (e.g. "Claude") →
**Create key**. Copy the `mpk_…` value now; it is shown only once.

Tick **Read only** if the assistant should only look at tickets.

## 2. Install

```bash
pip install -r requirements.txt        # needs Python 3.10+
```

## 3. Connect Claude

### Claude Code

```bash
claude mcp add mpira \
  -e MPIRA_URL=https://web-production-af909.up.railway.app \
  -e MPIRA_API_KEY=mpk_your_key_here \
  -- python "C:/path/to/ticket_mpira/tools/mpira-mcp/server.py"
```

### Claude Desktop

Edit `claude_desktop_config.json` (Settings → Developer → Edit config) and add:

```json
{
  "mcpServers": {
    "mpira": {
      "command": "python",
      "args": ["C:/path/to/ticket_mpira/tools/mpira-mcp/server.py"],
      "env": {
        "MPIRA_URL": "https://web-production-af909.up.railway.app",
        "MPIRA_API_KEY": "mpk_your_key_here"
      }
    }
  }
}
```

Restart Claude after saving.

## Tools

| Tool | What it does |
|---|---|
| `whoami` | Shows which Mpira user the key belongs to |
| `list_projects` | Projects you can access, with their keys |
| `my_issues` | Open issues assigned to you |
| `search_issues` | Text search, optionally per project or status |
| `get_issue` | Full details of an issue, e.g. `MPR-12` |
| `list_comments` | Comments on an issue |
| `create_issue` | Create an issue (type, priority, assignee, epic, parent, points, due date) |
| `update_issue` | Change title, description, priority, assignee, points, due date |
| `transition_issue` | Move an issue to another status (the workflow applies) |
| `add_comment` | Comment on an issue; `@handle` mentions people |

Example prompts: *"What are my open tickets in MPR?"*, *"Create a bug in MPR:
checkout total is off by one cent, high priority, assign to nikos"*,
*"Move MPR-14 to in progress and comment that I've started"*.

## Security notes

- Keys are stored only as a hash. Revoke a key on the Profile page at any time.
- A key has the same project access as its owner. Use a read-only key when
  writing isn't needed.
- Keep the key out of shared files. The configuration above stores it in
  your own Claude settings only.
