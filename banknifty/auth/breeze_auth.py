"""
SMB Algo - Breeze Auth - Updated with manual token entry and persistence
"""
import logging, os, re
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from core.accounts import get_all_accounts, update_session_token, clear_connection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth")
BREEZE_LOGIN_URL = "https://api.icicidirect.com/apiuser/login?api_key={api_key}"
ENV_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")

def persist_token(account_name, token):
    try:
        accounts = get_all_accounts()
        account_num = next((i for i, a in enumerate(accounts, 1) if a["name"] == account_name), None)
        if not account_num:
            return
        key = f"ACCOUNT{account_num}_SESSION_TOKEN"
        if os.path.exists(ENV_FILE):
            content = open(ENV_FILE).read()
            if key in content:
                content = re.sub(f"{key}=.*", f"{key}={token}", content)
            else:
                content += f"\n{key}={token}\n"
            open(ENV_FILE, "w").write(content)
            logger.info(f"Token persisted for {account_name}")
    except Exception as e:
        logger.error(f"Failed to persist token: {e}")

@router.get("/breeze/login/{account_name}")
async def breeze_login(account_name: str):
    accounts = {a["name"]: a for a in get_all_accounts()}
    if account_name not in accounts:
        return HTMLResponse(f"Account not found", status_code=404)
    api_key = accounts[account_name]["api_key"]
    return RedirectResponse(url=BREEZE_LOGIN_URL.format(api_key=api_key))

@router.get("/breeze/callback")
@router.post("/breeze/callback")
async def breeze_callback(request: Request):
    # Breeze sends token as ?apisession= query parameter
    token = request.query_params.get("apisession", "")
    html = open("/opt/smb-algo-bn/auth/callback.html").read()
    # Inject token into page so it auto-fills
    html = html.replace(
        "document.getElementById('status').textContent='Paste your session token below.';",
        f"document.getElementById('status').textContent='Paste your session token below.';"
    )
    if token:
        html = html.replace(
            "</script>",
            f"document.getElementById('tokenInput').value='{token}';"
            f"document.getElementById('status').className='status ok';"
            f"document.getElementById('status').textContent='Token captured! Click Activate Session.';"
            "</script>"
        )
    return HTMLResponse(html)

@router.post("/breeze/set-token")
async def set_session_token(request: Request):
    data = await request.json()
    account_name = data.get("account_name")
    token = data.get("session_token", "").strip()
    if not account_name or not token:
        return {"status": "error", "message": "Missing account_name or session_token"}
    update_session_token(account_name, token)
    clear_connection(account_name)
    persist_token(account_name, token)
    logger.info(f"Session activated for {account_name}")
    return {"status": "ok", "account": account_name, "message": "Session activated successfully"}

@router.get("/breeze/session-status")
async def session_status():
    from core.accounts import get_session_token
    accounts = get_all_accounts()
    return {"accounts": [{"name": a["name"], "has_token": bool(get_session_token(a["name"])), "paper_mode": a["paper_mode"], "active": a["active"]} for a in accounts]}
