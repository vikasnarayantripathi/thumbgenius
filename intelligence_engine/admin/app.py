import json
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from intelligence_engine.admin.auth import verify_credentials, create_token, verify_token
from intelligence_engine import database
from intelligence_engine.execution.version_store import (
    apply_suggestion, reject_suggestion, rollback_to_version, get_history
)
from intelligence_engine.execution.config_writer import load_active_config
from intelligence_engine.data.youtube_collector import fetch_all_niches
from intelligence_engine.brains.decision_engine import generate_suggestions
from intelligence_engine.maintenance.health_monitor import check as health_check

admin_app = FastAPI(title="ThumbGenius Intelligence Engine", docs_url=None)
bearer = HTTPBearer(auto_error=False)

# ── Auth helpers ──────────────────────────────────────────────
def get_current_admin(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = verify_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user

def get_admin_from_cookie(request: Request):
    token = request.cookies.get("ie_token")
    if not token:
        return None
    return verify_token(token)

# ── Login page ────────────────────────────────────────────────
@admin_app.get("/admin/login", response_class=HTMLResponse)
async def login_page():
    return _page("Login", """
        <div class="card" style="max-width:360px;margin:80px auto">
            <h2>Intelligence Engine</h2>
            <form method="post" action="/admin/login">
                <input name="username" placeholder="Username" required>
                <input name="password" type="password" placeholder="Password" required>
                <button type="submit">Sign in</button>
            </form>
        </div>
    """)

@admin_app.post("/admin/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if not verify_credentials(username, password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(username)
    resp = RedirectResponse("/admin/dashboard", status_code=302)
    resp.set_cookie("ie_token", token, httponly=True, max_age=86400)
    return resp

@admin_app.get("/admin/logout")
async def logout():
    resp = RedirectResponse("/admin/login", status_code=302)
    resp.delete_cookie("ie_token")
    return resp

# ── Dashboard ─────────────────────────────────────────────────
@admin_app.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not get_admin_from_cookie(request):
        return RedirectResponse("/admin/login")

    pending = await database.fetchrow("SELECT COUNT(*) as cnt FROM ie_suggestions WHERE status='pending'")
    deployed = await database.fetchrow("SELECT COUNT(*) as cnt FROM ie_suggestions WHERE status='deployed'")
    trends = await database.fetchrow("SELECT COUNT(*) as cnt FROM yt_trends WHERE fetched_at > NOW() - INTERVAL '24 hours'")
    config = load_active_config()

    content = f"""
        <h1>Intelligence Engine Dashboard</h1>
        <div class="metrics">
            <div class="metric">
                <span class="num">{pending['cnt']}</span>
                <span class="label">Pending suggestions</span>
            </div>
            <div class="metric">
                <span class="num">{deployed['cnt']}</span>
                <span class="label">Deployed</span>
            </div>
            <div class="metric">
                <span class="num">{trends['cnt']}</span>
                <span class="label">Trends (24h)</span>
            </div>
            <div class="metric">
                <span class="num">v{config.get('version',1)}</span>
                <span class="label">Config version</span>
            </div>
        </div>
        <div class="actions">
            <a href="/admin/suggestions" class="btn">Review Suggestions</a>
            <a href="/admin/config" class="btn secondary">Config History</a>
            <a href="/admin/run-job" class="btn secondary">Run Intelligence Job Now</a>
        </div>
    """
    return _page("Dashboard", content)

# ── Suggestions ───────────────────────────────────────────────
@admin_app.get("/admin/suggestions", response_class=HTMLResponse)
async def suggestions_page(request: Request):
    if not get_admin_from_cookie(request):
        return RedirectResponse("/admin/login")

    rows = await database.fetch("""
        SELECT id, title, description, reason, confidence, impact, risk, status, created_at
        FROM ie_suggestions
        ORDER BY created_at DESC LIMIT 50
    """)

    rows_html = ""
    for r in rows:
        badge_color = "#22c55e" if r['confidence'] >= 80 else "#f59e0b" if r['confidence'] >= 60 else "#ef4444"
        action_btns = ""
        if r['status'] == 'pending':
            action_btns = f"""
                <a href="/admin/suggestions/{r['id']}/approve" class="btn-sm approve">Approve</a>
                <a href="/admin/suggestions/{r['id']}/reject" class="btn-sm reject">Reject</a>
            """
        rows_html += f"""
            <tr>
                <td>{r['title']}</td>
                <td><span class="badge" style="background:{badge_color}">{r['confidence']}%</span></td>
                <td>{r['impact']}</td>
                <td>{r['risk']}</td>
                <td><span class="status {r['status']}">{r['status']}</span></td>
                <td>{action_btns}</td>
            </tr>
        """

    content = f"""
        <h1>Suggestions</h1>
        <a href="/admin/dashboard" class="btn secondary" style="margin-bottom:16px">← Back</a>
        <table>
            <thead><tr>
                <th>Title</th><th>Confidence</th><th>Impact</th>
                <th>Risk</th><th>Status</th><th>Actions</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
    """
    return _page("Suggestions", content)

@admin_app.get("/admin/suggestions/{sid}/approve")
async def approve(sid: int, request: Request):
    if not get_admin_from_cookie(request):
        return RedirectResponse("/admin/login")
    admin = get_admin_from_cookie(request)
    result = await apply_suggestion(sid, admin or "admin")
    return RedirectResponse("/admin/suggestions", status_code=302)

@admin_app.get("/admin/suggestions/{sid}/reject")
async def reject(sid: int, request: Request):
    if not get_admin_from_cookie(request):
        return RedirectResponse("/admin/login")
    admin = get_admin_from_cookie(request)
    await reject_suggestion(sid, admin or "admin")
    return RedirectResponse("/admin/suggestions", status_code=302)

# ── Config history ────────────────────────────────────────────
@admin_app.get("/admin/config", response_class=HTMLResponse)
async def config_page(request: Request):
    if not get_admin_from_cookie(request):
        return RedirectResponse("/admin/login")

    history = await get_history()
    current = load_active_config()

    rows_html = ""
    for h in history:
        active_badge = '<span class="badge" style="background:#22c55e">active</span>' if h['is_active'] else ''
        rows_html += f"""
            <tr>
                <td>v{h['version']} {active_badge}</td>
                <td>{str(h['applied_at'])[:16]}</td>
                <td>{h['applied_by'] or '-'}</td>
                <td>{h['rollback_reason'] or '-'}</td>
                <td>
                    {'<a href="/admin/config/rollback/' + str(h['version']) + '" class="btn-sm reject" onclick="return confirm(\'Rollback to v' + str(h['version']) + '?\')">Rollback</a>' if not h['is_active'] else ''}
                </td>
            </tr>
        """

    content = f"""
        <h1>Config History</h1>
        <a href="/admin/dashboard" class="btn secondary" style="margin-bottom:16px">← Back</a>
        <div class="card" style="margin-bottom:16px">
            <strong>Current active config (v{current.get('version',1)}):</strong>
            <pre>{json.dumps(current, indent=2)}</pre>
        </div>
        <table>
            <thead><tr><th>Version</th><th>Applied at</th><th>By</th><th>Note</th><th>Action</th></tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
    """
    return _page("Config History", content)

@admin_app.get("/admin/config/rollback/{version}")
async def rollback(version: int, request: Request):
    if not get_admin_from_cookie(request):
        return RedirectResponse("/admin/login")
    admin = get_admin_from_cookie(request)
    await rollback_to_version(version, "Manual rollback via admin panel", admin or "admin")
    return RedirectResponse("/admin/config", status_code=302)

# ── Trigger job manually ──────────────────────────────────────
@admin_app.get("/admin/run-job", response_class=HTMLResponse)
async def run_job(request: Request):
    if not get_admin_from_cookie(request):
        return RedirectResponse("/admin/login")
    await fetch_all_niches()
    await generate_suggestions()
    return RedirectResponse("/admin/suggestions", status_code=302)

# ── Internal API (main app uses these) ────────────────────────
@admin_app.get("/internal/config")
async def get_config():
    return load_active_config()

@admin_app.post("/internal/events")
async def log_event(request: Request):
    body = await request.json()
    await database.execute("""
        INSERT INTO user_events (user_id, event_type, niche, payload)
        VALUES ($1, $2, $3, $4)
    """,
        body.get('user_id', 'anonymous'),
        body.get('event_type', 'unknown'),
        body.get('niche', ''),
        json.dumps(body.get('payload', {}))
    )
    return {"ok": True}

@admin_app.get("/admin/health")
async def health(request: Request):
    if not get_admin_from_cookie(request):
        return RedirectResponse("/admin/login")
    report = await health_check()
    return JSONResponse(report)

# ── HTML template ─────────────────────────────────────────────
def _page(title: str, content: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} — IE Admin</title>
    <style>
        *{{box-sizing:border-box;margin:0;padding:0}}
        body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;padding:24px}}
        h1{{font-size:22px;font-weight:600;margin-bottom:20px;color:#f8fafc}}
        h2{{font-size:18px;font-weight:500;margin-bottom:16px}}
        .card{{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:20px;margin-bottom:16px}}
        .metrics{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px}}
        .metric{{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:20px;min-width:140px}}
        .metric .num{{display:block;font-size:32px;font-weight:700;color:#38bdf8}}
        .metric .label{{font-size:12px;color:#94a3b8;margin-top:4px}}
        .actions{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px}}
        .btn{{background:#3b82f6;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none;font-size:14px;border:none;cursor:pointer}}
        .btn.secondary{{background:#1e293b;border:1px solid #334155;color:#e2e8f0}}
        .btn-sm{{padding:5px 12px;border-radius:6px;font-size:12px;text-decoration:none;display:inline-block}}
        .btn-sm.approve{{background:#22c55e;color:#fff}}
        .btn-sm.reject{{background:#ef4444;color:#fff}}
        table{{width:100%;border-collapse:collapse;background:#1e293b;border-radius:10px;overflow:hidden}}
        th{{background:#0f172a;padding:12px 16px;text-align:left;font-size:12px;color:#94a3b8;text-transform:uppercase}}
        td{{padding:12px 16px;border-top:1px solid #1e293b;font-size:14px}}
        tr:hover td{{background:#243248}}
        .badge{{padding:3px 10px;border-radius:20px;font-size:12px;color:#fff;font-weight:600}}
        .status.pending{{color:#f59e0b}}
        .status.deployed{{color:#22c55e}}
        .status.rejected{{color:#ef4444}}
        input,select{{width:100%;padding:10px;margin-bottom:12px;background:#0f172a;border:1px solid #334155;border-radius:8px;color:#e2e8f0;font-size:14px}}
        pre{{background:#0f172a;padding:16px;border-radius:8px;overflow-x:auto;font-size:12px;color:#94a3b8;margin-top:8px}}
        a{{color:#38bdf8}}
        nav{{display:flex;gap:16px;margin-bottom:28px;padding-bottom:16px;border-bottom:1px solid #1e293b}}
        nav a{{color:#94a3b8;text-decoration:none;font-size:14px}}
        nav a:hover{{color:#f8fafc}}
    </style>
</head>
<body>
    <nav>
        <a href="/admin/dashboard">Dashboard</a>
        <a href="/admin/suggestions">Suggestions</a>
        <a href="/admin/config">Config</a>
        <a href="/admin/health">Health</a>
        <a href="/admin/logout" style="margin-left:auto;color:#ef4444">Logout</a>
    </nav>
    {content}
</body>
</html>"""
