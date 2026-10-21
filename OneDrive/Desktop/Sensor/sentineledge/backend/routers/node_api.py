"""
routers/node_api.py — setup and status for a company node (node role only).

  GET  /node-setup          small page to pair this server with the hub
  POST /api/node/pair       {hub_url, pairing_code, node_name} → pairs
  GET  /api/node/status     paired? connected? queue size?
  POST /api/node/unpair     forget the hub (this PC only)

Pairing is only accepted from this PC or its local/Tailscale network, because it
runs before any admin account exists on a fresh node.
"""

import ipaddress

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from middleware.rate_limit import limiter
from services import license, node_agent, outbox
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["Node"])

_TAILSCALE = ipaddress.ip_network("100.64.0.0/10")


def _trusted_network(request: Request, loopback_only: bool = False) -> None:
    host = request.client.host if request.client else ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise HTTPException(status_code=403, detail="Not allowed")
    if ip.is_loopback:
        return
    if loopback_only or not (ip.is_private or ip in _TAILSCALE):
        raise HTTPException(status_code=403, detail="Do this from the node PC itself or its local network")


class _PairIn(BaseModel):
    hub_url:      str = Field(min_length=8, max_length=200)
    pairing_code: str = Field(min_length=8, max_length=40)
    node_name:    str = Field(default="", max_length=100)


@router.post("/api/node/pair")
@limiter.limit("10/minute")
async def pair(body: _PairIn, request: Request):
    paired = node_agent.load_pairing()
    _trusted_network(request, loopback_only=bool(paired))   # re-pairing only from the PC itself
    import asyncio, socket
    try:
        co = await asyncio.to_thread(node_agent.pair_with_hub, body.hub_url, body.pairing_code,
                                     body.node_name or socket.gethostname())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "paired", "company": co}


@router.get("/api/node/status")
async def status(request: Request):
    _trusted_network(request)
    p = node_agent.load_pairing()
    return {
        "paired": bool(p),
        "hub_url": p["hub_url"] if p else None,
        "company": {"id": p["company_id"], "name": p["company_name"]} if p else None,
        "connected": node_agent.agent.state["connected"],
        "last_ok": node_agent.agent.state["last_ok"],
        "last_error": node_agent.agent.state["last_error"],
        "sent_total": node_agent.agent.state["sent_total"],
        "queued": outbox.pending_count(),
        "license_ok": license.check()[0],
        "license_message": license.check()[1] or None,
    }


class _HubUrlIn(BaseModel):
    hub_url: str = Field(min_length=8, max_length=200)


@router.post("/api/node/hub-url")
async def change_hub_url(body: _HubUrlIn, request: Request):
    """The hub moved (new IP / Tailscale name)? Point this node at it without re-pairing.
    The node key stays; the hub still has to accept it. This PC only."""
    _trusted_network(request, loopback_only=True)
    if not node_agent.load_pairing():
        raise HTTPException(status_code=409, detail="Not paired yet — use Connect instead")
    import asyncio, requests
    try:
        base = node_agent.normalise_hub_url(body.hub_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    def _check() -> bool:
        r = requests.get(f"{base}/api/hub/ping", timeout=node_agent.HTTP_TIMEOUT)
        return r.status_code == 200 and r.json().get("service") == "sentineledge-hub"
    try:
        ok = await asyncio.to_thread(_check)
    except Exception:
        raise HTTPException(status_code=502, detail=f"Could not reach a hub at {base}")
    if not ok:
        raise HTTPException(status_code=422, detail="That address is not a SentinelEdge hub")
    node_agent._set_setting("hub_url", base)
    node_agent.agent.wake()
    return {"status": "updated", "hub_url": base}


@router.post("/api/node/unpair")
async def unpair(request: Request):
    _trusted_network(request, loopback_only=True)
    node_agent.unpair()
    return {"status": "unpaired"}


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Connect this server to the hub</title>
<style>
body{font:15px/1.5 system-ui,Segoe UI,sans-serif;background:#f4f5f9;color:#1f2430;margin:0;padding:24px}
main{max-width:520px;margin:0 auto;background:#fff;border-radius:12px;padding:28px;box-shadow:0 1px 4px #0001}
h1{font-size:20px;margin:0 0 4px}p{color:#5b6270;margin:4px 0 18px}label{display:block;font-weight:600;margin:14px 0 4px}
input{width:100%;box-sizing:border-box;padding:10px;border:1px solid #cdd2dc;border-radius:8px;font:inherit}
button{margin-top:20px;padding:10px 18px;border:0;border-radius:8px;background:#6d28d9;color:#fff;font:inherit;font-weight:600;cursor:pointer}
#msg{margin-top:16px;padding:10px;border-radius:8px;display:none}.ok{background:#dcfce7;color:#166534}.err{background:#fee2e2;color:#991b1b}
.box{background:#f4f5f9;border-radius:8px;padding:10px;margin-top:10px;font-size:13px}
</style></head><body><main>
<h1>Connect this server to the hub</h1>
<p>Ask your Super Admin for the hub address and a one-time pairing code.</p>
<div id="state" class="box">Checking…</div>
<label for="hub">Hub address</label><input id="hub" placeholder="http://100.x.y.z:5000">
<label for="code">Pairing code</label><input id="code" placeholder="ABCD-EFGH-JKLM" autocomplete="off">
<button id="go">Connect</button><div id="msg"></div>
<p style="margin-top:22px;font-size:13px">Already connected but the hub's address changed? Enter the new address above and press
<a href="#" id="chg">Change hub address</a> (no new code needed; this PC only).</p>
<script>
const $=id=>document.getElementById(id), msg=(t,c)=>{const m=$('msg');m.className=c;m.textContent=t;m.style.display='block'};
async function refresh(){try{const r=await (await fetch('/api/node/status')).json();
 $('state').textContent=r.paired?('Paired with '+r.hub_url+' as '+r.company.name+' — '+(r.connected?'connected':'not connected'+(r.last_error?': '+r.last_error:''))+' · '+r.queued+' waiting to send'):'Not paired yet.'}
 catch(e){$('state').textContent='Could not read status'}}
$('go').onclick=async()=>{msg('Connecting…','box');
 const r=await fetch('/api/node/pair',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hub_url:$('hub').value,pairing_code:$('code').value})});
 const d=await r.json().catch(()=>({}));
 if(r.ok){msg('Connected as '+d.company.name,'ok');$('code').value=''}else msg(d.detail||'Failed','err'); refresh()};
$('chg').onclick=async e=>{e.preventDefault();msg('Checking…','box');
 const r=await fetch('/api/node/hub-url',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hub_url:$('hub').value})});
 const d=await r.json().catch(()=>({}));
 if(r.ok)msg('Hub address updated to '+d.hub_url,'ok');else msg(d.detail||'Failed','err');refresh()};
refresh();setInterval(refresh,5000);
</script></main></body></html>"""


@router.get("/node-setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    _trusted_network(request)
    return HTMLResponse(_PAGE)
