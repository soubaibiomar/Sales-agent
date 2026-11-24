"""
Live check of model-driven tool calling (inspection finding F-17).

Seeds a throwaway in-memory database with one order and one product, then runs real
agent turns on the local qwen3.5:4b model. Records which tools the model chose, with
which arguments, and the guarded final answer. Non-deterministic by nature: this is
evidence of behaviour, not a unit test.

Usage: python scripts/live_agent_tool_calling_check.py <output.json>
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.backend.models.entities import Base, Tenant, SalesOrder, Product, Warehouse, InventoryItem  # noqa: E402
from src.ai.agents.base import AgentInput  # noqa: E402
from src.ai.agents.interactive.order import OrderPaymentAgent  # noqa: E402
from src.ai.agents.interactive.product import ProductKnowledgeAgent  # noqa: E402
from src.ai.tool_gateway import ServerSecurityContext  # noqa: E402

CASES = [
    (OrderPaymentAgent, "Bonjour, quel est le statut de ma commande SO-778 ?"),
    (OrderPaymentAgent, "Where is my order SO-999?"),            # order does not exist
    (ProductKnowledgeAgent, "Est-ce que le SKU PANEL-400 est disponible en stock ?"),
    (ProductKnowledgeAgent, "Bonjour, merci pour votre aide."),   # no tool needed
]


async def main(out_path: str) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with factory() as s:
        s.add(Tenant(id="t_live", name="Live", slug="live"))
        s.add(SalesOrder(id="o1", tenant_id="t_live", order_number="SO-778", terms_hash="h", grand_total_cents=250000,
                         currency="MAD", status="SHIPPED", payment_status="PAID"))
        s.add(Product(id="p1", tenant_id="t_live", sku="PANEL-400", name="Panneau solaire 400W", base_price_cents=125000))
        s.add(Warehouse(id="w1", tenant_id="t_live", code="CASA", name="Casablanca"))
        s.add(InventoryItem(tenant_id="t_live", warehouse_id="w1", product_id="p1", sku="PANEL-400",
                            on_hand_quantity=12, reserved_quantity=2, allocated_quantity=0))
        await s.commit()
    ctx = ServerSecurityContext(tenant_id="t_live", user_id="u", role="customer", end_user_roles=["customer"])
    results = []
    for agent_cls, prompt in CASES:
        agent = agent_cls()
        async with factory() as s:
            t0 = time.perf_counter()
            out = await agent.execute(AgentInput(conversation_id="c", turn_id="t", user_prompt=prompt), ctx, db_session=s)
            dt = round((time.perf_counter() - t0) * 1000)
        results.append({
            "agent": agent.role_id, "prompt": prompt, "latency_ms": dt, "status": out.status,
            "tools_called": [{k: v for k, v in tc.items() if k != "result"} | {"ok": tc.get("result") is not None} for tc in out.tools_called],
            "response": out.response_text[:300],
        })
        print(json.dumps(results[-1], ensure_ascii=False))
    await engine.dispose()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"model": "qwen3.5:4b (live, non-deterministic)", "results": results}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "evidence/claude-inspection/benchmarks/live_agent_tool_calling.json"))
