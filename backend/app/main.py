from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .excel_io import load_orders_from_excel, machines_to_dataframe, write_schedule_outputs
from .machines import built_in_machines
from .models import ScheduleRunConfig
from .scheduler import preview_schedule, run_schedule


WORKSPACE_DIR = Path(__file__).resolve().parents[2]
UPLOAD_DIR = WORKSPACE_DIR / "uploads"
OUTPUT_DIR = WORKSPACE_DIR / "outputs"


class RunScheduleRequest(BaseModel):
    upload_id: str
    config: ScheduleRunConfig | None = None


app = FastAPI(title="Blown Film Scheduler MVP", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/machines")
def get_machines() -> dict:
    machines = built_in_machines()
    return {
        "count": len(machines),
        "machines": [machine.model_dump(mode="json") for machine in machines],
    }


@app.post("/api/schedule/preview")
async def schedule_preview(file: UploadFile = File(...)) -> dict:
    upload_path = _save_upload(file)
    orders, issues = load_orders_from_excel(upload_path)
    machines = built_in_machines()
    summary, audit, validation_issues = preview_schedule(orders, machines, issues)
    return {
        "upload_id": upload_path.stem,
        "summary": summary.model_dump(mode="json"),
        "validation_issues": [item.model_dump(mode="json") for item in validation_issues],
        "audit": [item.model_dump(mode="json") for item in audit],
        "orders": [item.model_dump(mode="json") for item in orders],
        "machines": [item.model_dump(mode="json") for item in machines],
    }


@app.post("/api/schedule/run")
def schedule_run(payload: RunScheduleRequest) -> dict:
    upload_path = UPLOAD_DIR / f"{payload.upload_id}.xlsx"
    if not upload_path.exists():
        raise HTTPException(status_code=404, detail="上传文件不存在，请重新上传订单 Excel")

    orders, issues = load_orders_from_excel(upload_path)
    machines = built_in_machines()
    result = run_schedule(orders, machines, issues, payload.config)
    export_id = str(uuid4())[:8]
    result.export_id = export_id
    write_schedule_outputs(result, OUTPUT_DIR, export_id)
    return result.as_jsonable()


@app.get("/api/schedule/export/{export_id}/{kind}")
def export_file(export_id: str, kind: str) -> FileResponse:
    suffix_by_kind = {
        "schedule": "schedule_result.xlsx",
        "audit": "constraint_audit.xlsx",
        "report": "schedule_report.md",
    }
    if kind not in suffix_by_kind:
        raise HTTPException(status_code=400, detail="导出类型必须是 schedule、audit 或 report")
    path = OUTPUT_DIR / f"{export_id}_{suffix_by_kind[kind]}"
    if not path.exists():
        raise HTTPException(status_code=404, detail="导出文件不存在")
    media_type = "text/markdown" if kind == "report" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get("/api/examples/mock-orders")
def download_mock_orders() -> FileResponse:
    path = WORKSPACE_DIR / "examples" / "blownfilm_mvp_mock_v2.xlsx"
    if not path.exists():
        raise HTTPException(status_code=404, detail="模拟订单文件尚未生成")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )


@app.get("/api/machines/export")
def export_machines() -> FileResponse:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "built_in_machines.xlsx"
    machines_to_dataframe(built_in_machines()).to_excel(path, index=False)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )


def _save_upload(file: UploadFile) -> Path:
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 订单工作簿")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    upload_id = str(uuid4())[:8]
    path = UPLOAD_DIR / f"{upload_id}.xlsx"
    with path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return path
