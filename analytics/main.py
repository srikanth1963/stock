"""
main.py — SMB Algo Analytics FastAPI Application
Port: 8003
URL: trading.smbenablers.com/analytics/
"""
import logging
import os
import sys

sys.path.insert(0, '/opt/smb-algo-stocks')
sys.path.insert(0, '/opt/smb-algo-analytics')

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from analytics_engine import router as analytics_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="SMB Algo Analytics")
app.include_router(analytics_router, prefix="/analytics")


@app.get("/analytics/charts/", response_class=HTMLResponse)
async def serve_charts():
    charts_path = "/opt/smb-algo-analytics/charts.html"
    if os.path.exists(charts_path):
        return HTMLResponse(open(charts_path).read())
    return HTMLResponse("<h1>Charts coming soon</h1>")

@app.get("/analytics/", response_class=HTMLResponse)
async def serve_analytics():
    html_path = "/opt/smb-algo-analytics/analytics.html"
    if os.path.exists(html_path):
        return HTMLResponse(open(html_path).read())
    return HTMLResponse("<h1>SMB Algo Analytics</h1><p>analytics.html not found</p>")


@app.get("/analytics/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8003, reload=False)
