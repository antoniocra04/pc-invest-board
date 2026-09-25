import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date as Date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import dns, portfolio
from .config import Settings
from .db import Database
from .updater import Updater

STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class ComponentIn(BaseModel):
    name: str | None = None
    category: str = ""
    url: str | None = None
    purchase_price: float = Field(gt=0)
    purchase_date: Date | None = None
    quantity: int = Field(default=1, ge=1)


class ComponentPatch(BaseModel):
    name: str | None = None
    category: str | None = None
    url: str | None = None
    purchase_price: float | None = Field(default=None, gt=0)
    purchase_date: Date | None = None
    quantity: int | None = Field(default=None, ge=1)


class PriceIn(BaseModel):
    price: float = Field(gt=0)
    date: Date | None = None


class CaptureIn(BaseModel):
    url: str
    price: float | None = None
    name: str | None = None


class RefreshIn(BaseModel):
    component_id: int | None = None


class ImportIn(BaseModel):
    components: list[ComponentIn]


def create_app(settings: Settings | None = None, fetch=None) -> FastAPI:
    settings = settings or Settings()
    db = Database(settings.db_path)
    updater = Updater(settings, db, **({"fetch": fetch} if fetch else {}))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(updater.schedule_forever()) if settings.scheduler_enabled else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="PC Invest Board", lifespan=lifespan)
    app.state.db = db
    app.state.updater = updater

    def component_or_404(component_id: int) -> dict:
        component = db.get_component(component_id)
        if not component:
            raise HTTPException(404, "Комплектующее не найдено")
        return component

    def normalized(data: dict) -> dict:
        if "url" in data:
            url = (data["url"] or "").strip() or None
            data["url"] = url
            data["product_code"] = dns.product_code(url)
            if url and not data["product_code"]:
                raise HTTPException(422, "Ссылка должна вести на товар DNS: https://www.dns-shop.ru/product/…")
        if data.get("purchase_date") is not None:
            data["purchase_date"] = data["purchase_date"].isoformat()
        if "name" in data:
            data["name"] = (data["name"] or "").strip()
        return data

    def prepare_component(body: ComponentIn) -> dict:
        data = normalized(body.model_dump())
        data["purchase_date"] = data["purchase_date"] or settings.now().date().isoformat()
        if not data["name"]:
            if not data["product_code"]:
                raise HTTPException(422, "Укажи название или ссылку на DNS")
            data["name"] = f"Товар DNS {data['product_code']}"
            data["name_auto"] = 1
        return data

    def insert_component(data: dict) -> dict:
        return db.get_component(db.add_component(data, settings.now().isoformat()))

    # --- API --------------------------------------------------------------

    @app.get("/api/portfolio")
    def get_portfolio():
        result = portfolio.build(db.list_components(), db.list_prices(), settings.now().date())
        result["status"] = updater.status
        return result

    @app.get("/api/status")
    def get_status():
        return updater.status

    @app.post("/api/components", status_code=201)
    async def add_component(body: ComponentIn):
        component = insert_component(prepare_component(body))
        if component["product_code"]:
            updater.start([component["id"]])
        return component

    @app.put("/api/components/{component_id}")
    async def update_component(component_id: int, body: ComponentPatch):
        before = component_or_404(component_id)
        data = normalized(body.model_dump(exclude_unset=True))
        if data.get("name"):
            data["name_auto"] = 0
        elif "name" in data:
            del data["name"]
        db.update_component(component_id, data)
        after = db.get_component(component_id)
        if after["product_code"] and after["product_code"] != before["product_code"]:
            updater.start([component_id])
        return after

    @app.delete("/api/components/{component_id}", status_code=204)
    def delete_component(component_id: int):
        if not db.delete_component(component_id):
            raise HTTPException(404, "Комплектующее не найдено")

    @app.get("/api/components/{component_id}")
    def component_details(component_id: int):
        component = component_or_404(component_id)
        prices = db.list_prices(component_id)
        return {
            **portfolio.component_summary(component, prices),
            "series": [{"date": d, "price": p} for d, p in portfolio.component_series(component, prices)],
            "history": list(reversed(prices)),
            "debug": (settings.debug_dir / f"{component_id}.png").exists(),
        }

    DEBUG_TYPES = {"png": "image/png", "html": "text/plain; charset=utf-8", "json": "application/json"}

    @app.get("/api/components/{component_id}/debug.{kind}", include_in_schema=False)
    def component_debug(component_id: int, kind: str):
        """What the browser saw on the last failed check (HTML is served as text, never rendered)."""
        path = settings.debug_dir / f"{component_id}.{kind}"
        if kind not in DEBUG_TYPES or not path.exists():
            raise HTTPException(404, "Снимка нет")
        return FileResponse(path, media_type=DEBUG_TYPES[kind])

    @app.post("/api/components/{component_id}/prices", status_code=201)
    def add_manual_price(component_id: int, body: PriceIn):
        component_or_404(component_id)
        checked_at = f"{body.date.isoformat()}T12:00:00" if body.date else settings.now().isoformat()
        return {"id": db.add_price(component_id, checked_at, body.price, True, "manual")}

    @app.delete("/api/prices/{price_id}", status_code=204)
    def delete_price(price_id: int):
        if not db.delete_price(price_id):
            raise HTTPException(404, "Запись не найдена")

    @app.post("/api/refresh", status_code=202)
    async def refresh(body: RefreshIn | None = None):
        ids = None
        if body and body.component_id is not None:
            component = component_or_404(body.component_id)
            if not component["product_code"]:
                raise HTTPException(422, "У этого комплектующего нет ссылки на DNS")
            ids = [body.component_id]
        if not updater.start(ids):
            raise HTTPException(409, "Обновление уже идёт")
        return updater.status

    @app.post("/api/capture")
    def capture(body: CaptureIn):
        """Price sent by the bookmarklet from a DNS page opened in the user's own browser."""
        code = dns.product_code(body.url)
        if not code:
            raise HTTPException(422, "Это не страница товара DNS")
        component = db.find_by_product_code(code)
        if not component:
            return {"matched": False, "url": body.url, "name": body.name, "price": body.price}
        if body.name and component["name_auto"]:
            db.update_component(component["id"], {"name": body.name.strip(), "name_auto": 0})
        if body.price:
            db.add_price(component["id"], settings.now().isoformat(), body.price, True, "bookmarklet")
        return {"matched": True, "component": db.get_component(component["id"]), "price": body.price}

    @app.get("/api/export")
    def export():
        return {"components": db.list_components(), "prices": db.list_prices()}

    @app.post("/api/import", status_code=201)
    async def import_components(body: ImportIn):
        """Bulk add purchases: [{name, url, category, purchase_price, purchase_date, quantity}, ...]."""
        prepared = [prepare_component(item) for item in body.components]  # validate everything first
        created = [insert_component(data) for data in prepared]
        if any(c["product_code"] for c in created):
            updater.start([c["id"] for c in created if c["product_code"]])
        return {"created": len(created)}

    # --- UI ---------------------------------------------------------------

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app
