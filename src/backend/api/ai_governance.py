"""
AI Governance, Model Gateway, RAG and Tool Gateway API Routes.
Step 08: Model Gateway, RAG, Router, Protected Tools and Output Verification
(Controls 39-40, 49, 63, 65-67; SAI-06 to SAI-12; ADR-008)
"""
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import require_permission, SecurityContext
from src.ai.model_gateway import (
    model_gateway,
    ModelGatewayRequest,
    ModelGatewayResponse
)
from src.ai.rag.models import (
    DocumentIngestRequest,
    DocumentResponse,
    RAGQueryRequest,
    RAGChunkResult
)
from src.ai.rag.service import KnowledgeService, EmbeddingUnavailableError
from src.ai.router import ConversationRouter, RoutingDecision
from src.ai.tool_gateway import (
    tool_gateway,
    ServerSecurityContext,
    UnauthorizedToolError,
    TenantMismatchError,
    SchemaValidationError,
    DeadlineExceededError,
    DomainServiceRejectedError
)
from src.ai.output_guard import (
    OutputGuard,
    EvidenceEnvelope,
    OutputGuardResult
)
from src.ai.evaluations.evaluator import ModelEvaluator, EvaluationReport

router = APIRouter(prefix="/api/v1/ai", tags=["AI Governance"])


@router.get("/health")
async def get_ai_health(
    ctx: SecurityContext = Depends(require_permission("ai:manage"))
):
    """Returns Model Gateway health, active models, VRAM headroom, and budgets."""
    return await model_gateway.get_health()


@router.post("/generate", response_model=ModelGatewayResponse)
async def generate_completion(
    req: ModelGatewayRequest,
    ctx: SecurityContext = Depends(require_permission("ai:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    """Executes bounded generation with PII redaction and execution ledger logging."""
    # Force tenant_id from authenticated SecurityContext
    req.tenant_id = ctx.tenant_id
    return await model_gateway.generate(req, db_session=db)


@router.post("/route", response_model=RoutingDecision)
async def route_conversation(
    payload: Dict[str, Any],
    ctx: SecurityContext = Depends(require_permission("crm:read"))
):
    """
    Classifies language (5 matrices), intent, execution class, and adversarial risk.
    """
    text = payload.get("text", "")
    turn_id = payload.get("turn_id")
    is_human_owned = payload.get("is_human_owned", False)

    return ConversationRouter.route(
        text=text,
        turn_id=turn_id,
        is_human_owned=is_human_owned
    )


@router.post("/tools/execute")
async def execute_agent_tool(
    payload: Dict[str, Any],
    ctx: SecurityContext = Depends(require_permission("ai:tools")),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Protected tool gateway execution endpoint.
    Enforces role allowlist and injects server-issued security context.
    """
    tool_name = payload.get("tool_name")
    params = payload.get("params", {})
    if not tool_name:
        raise HTTPException(status_code=400, detail="Missing required 'tool_name'")

    # Invariant: Server-issued security context (never trust tenant/user from client)
    primary_role = payload.get("agent_role") or (ctx.roles[0] if ctx.roles else "customer")
    sec_context = ServerSecurityContext(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role=primary_role,
        permissions=ctx.permissions,
        end_user_roles=list(ctx.roles)
    )

    try:
        result = await tool_gateway.execute_tool(
            tool_name=tool_name,
            params=params,
            context=sec_context,
            db_session=db
        )
        return {"status": "SUCCESS", "tool": tool_name, "result": result}
    except UnauthorizedToolError as ute:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(ute))
    except (TenantMismatchError, SchemaValidationError) as se:
        raise HTTPException(status_code=422, detail=str(se))
    except DeadlineExceededError as de:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(de))
    except DomainServiceRejectedError as dsr:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(dsr))


@router.post("/rag/documents", response_model=DocumentResponse)
async def ingest_knowledge_document(
    req: DocumentIngestRequest,
    ctx: SecurityContext = Depends(require_permission("ai:rag")),
    db: AsyncSession = Depends(get_db_session)
):
    """Ingests and indexes an approved document with anti-poisoning checks."""
    service = KnowledgeService(db)
    return await service.ingest_document(
        tenant_id=ctx.tenant_id,
        req=req,
        user_id=ctx.user_id
    )


@router.get("/rag/documents", response_model=List[DocumentResponse])
async def list_knowledge_documents(
    status: Optional[str] = Query(None),
    ctx: SecurityContext = Depends(require_permission("ai:rag")),
    db: AsyncSession = Depends(get_db_session)
):
    """Lists knowledge documents for the current tenant."""
    service = KnowledgeService(db)
    return await service.list_documents(tenant_id=ctx.tenant_id, status=status)


@router.delete("/rag/documents/{document_id}")
async def tombstone_knowledge_document(
    document_id: str,
    ctx: SecurityContext = Depends(require_permission("ai:rag")),
    db: AsyncSession = Depends(get_db_session)
):
    """Tombstones a knowledge document and purges its chunks from retrieval."""
    service = KnowledgeService(db)
    success = await service.tombstone_document(tenant_id=ctx.tenant_id, document_id=document_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"status": "TOMBSTONED", "document_id": document_id}


@router.post("/rag/query", response_model=List[RAGChunkResult])
async def query_knowledge_base(
    req: RAGQueryRequest,
    ctx: SecurityContext = Depends(require_permission("crm:read")),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Executes permission-filtered semantic retrieval strictly isolated to tenant
    and document ACL roles.
    """
    service = KnowledgeService(db)
    # F-18: document ACL roles come ONLY from the verified identity; client-supplied
    # user_roles are ignored (they previously let a caller self-assign e.g. "board_only").
    req.user_roles = list(ctx.roles)
    try:
        return await service.retrieve_context(tenant_id=ctx.tenant_id, req=req)
    except EmbeddingUnavailableError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))


@router.post("/guard/verify", response_model=OutputGuardResult)
async def verify_output_claims(
    payload: Dict[str, Any],
    ctx: SecurityContext = Depends(require_permission("crm:read"))
):
    """
    Inspects candidate model text, redacts PII, verifies claims against
    EvidenceEnvelope, and appends statutory AI disclosure.
    """
    text = payload.get("text", "")
    raw_evidence = payload.get("evidence")
    evidence = None
    if raw_evidence:
        evidence = EvidenceEnvelope(**raw_evidence)

    include_disclosure = payload.get("include_disclosure", True)
    return OutputGuard.inspect_and_guard(
        text=text,
        evidence=evidence,
        include_disclosure=include_disclosure
    )


@router.get("/evaluations/run", response_model=EvaluationReport)
async def run_offline_evaluations(
    ctx: SecurityContext = Depends(require_permission("ai:manage"))
):
    """Executes offline evaluation suite across defense, routing, and grounding."""
    return await ModelEvaluator.run_evaluation()
