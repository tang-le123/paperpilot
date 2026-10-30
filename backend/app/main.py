"""PaperPilot FastAPI application."""
from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pymupdf
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.auth import (
    ensure_default_user,
    login,
    refresh_access,
    register,
    user_from_token,
)
from app.config import (
    CITATION_SUPPORT_THRESHOLD,
    MAX_PAPERS,
    MAX_UPLOAD_MB,
    QUERY_REWRITE_ENABLED,
    SECTION_FILTER_ENABLED,
    SUPPORTED_EXTENSIONS,
    UPLOAD_DIR,
)
from app.db import (
    create_collection,
    create_paper,
    delete_chunks,
    delete_collection,
    delete_paper,
    get_chunk,
    get_chunks,
    get_collection,
    get_neighbors,
    get_paper,
    get_sections,
    init_db,
    list_collections,
    list_papers,
    move_paper,
    rename_collection,
    update_paper,
)
from app.glossary import lookup
from app.indexing import EmbeddingService, HybridRetriever, PaperIndex, Reranker
from app.query import classify as classify_query
from app.query import rewrite as rewrite_query
from app.query import sections as query_sections
from app.llm import (
    answer_compare,
    answer_explain,
    answer_innovation,
    build_claim_checks,
    build_stream_prompt,
    clean_citations,
    generate_answer,
    repair_partial_answer,
    stream_complete,
    strip_citation_markers,
    support_gate_message,
    summarize_papers,
    verify_citations,
)
from app.llm import _citations_from_answer, _claim_for_marker, _renumber_citations
from app.router import Strategy, route
from app.schemas import (
    AuthRequest,
    AuthResponse,
    ChatRequest,
    ChatResponse,
    CollectionCreate,
    CollectionRead,
    PaperMove,
    PaperRead,
    RefreshRequest,
    SectionRead,
    SummaryRequest,
    SummaryResponse,
    UploadResponse,
)
from app.services import process_paper


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_default_user()
    app.state.embedder = EmbeddingService()
    app.state.index = PaperIndex()
    app.state.reranker = Reranker()
    app.state.retriever = HybridRetriever(
        app.state.embedder, app.state.index, app.state.reranker
    )
    yield


app = FastAPI(
    title="PaperPilot",
    version="0.1.0",
    description="Upload papers and ask questions with page-level citations.",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/docs", include_in_schema=False)
async def local_swagger_ui() -> HTMLResponse:
    return HTMLResponse(
        """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>PaperPilot - Swagger UI</title>
  <link rel="stylesheet" href="/static/swagger/swagger-ui.css" />
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="/static/swagger/swagger-ui-bundle.js"></script>
  <script src="/static/swagger/swagger-ui-standalone-preset.js"></script>
  <script>
    window.ui = SwaggerUIBundle({
      url: "/openapi.json",
      dom_id: "#swagger-ui",
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
      layout: "BaseLayout",
      deepLinking: true
    });
  </script>
</body>
</html>"""
    )


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


def require_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    user = user_from_token(authorization.removeprefix("Bearer ").strip())
    if user is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return user


def owned_paper(paper_id: int, user_id: int) -> dict:
    item = get_paper(paper_id)
    if item is None or item.get("owner_id") != user_id:
        raise HTTPException(status_code=404, detail="论文不存在")
    return item


def expand_with_neighbors(chunks: list[dict], *, max_extra: int = 3) -> list[dict]:
    """Add one chunk on each side for answer context, never for retrieval scoring."""
    if not chunks:
        return chunks
    seen = {chunk["chunk_id"] for chunk in chunks}
    extra = []
    for chunk in chunks:
        if len(extra) >= max_extra:
            break
        try:
            neighbors = get_neighbors(
                int(chunk["paper_id"]), int(chunk.get("chunk_index", 0))
            )
        except Exception:
            continue
        for neighbor in neighbors:
            if neighbor["chunk_id"] in seen:
                continue
            seen.add(neighbor["chunk_id"])
            extra.append(neighbor)
            if len(extra) >= max_extra:
                break
    return chunks + extra


async def finalize_with_citations(
    answer: str,
    citations: list,
    language: str,
    retriever=None,
) -> tuple[str, list, float | None, bool]:
    """Verify, repair partial claims, remove unsupported markers and gate."""
    if not citations:
        return answer, citations, None, False

    citations, support_rate = await verify_citations(answer, citations)
    partial_indices = [
        index for index, citation in enumerate(citations, 1)
        if citation.support == "partial"
    ]
    # Only pay for repair/second retrieval when the answer would actually be gated.
    if partial_indices and (
        support_rate is not None and support_rate < CITATION_SUPPORT_THRESHOLD
    ):
        extra_chunks = []
        if retriever is not None:
            seen: set[str] = set()
            for index in partial_indices[:2]:
                citation = citations[index - 1]
                claim = _claim_for_marker(answer, f"[{index}]")
                if not claim:
                    continue
                try:
                    found = retriever.retrieve([citation.paper_id], claim, top_k=2)
                except Exception:
                    found = []
                for chunk in found:
                    if chunk["chunk_id"] not in seen:
                        seen.add(chunk["chunk_id"])
                        extra_chunks.append(chunk)
                        if len(extra_chunks) >= 4:
                            break
                if len(extra_chunks) >= 4:
                    break
        repaired = await repair_partial_answer(
            answer, citations, language, extra_chunks=extra_chunks
        )
        if repaired and repaired != answer:
            answer = repaired
            citations, support_rate = await verify_citations(answer, citations)

    answer, citations = clean_citations(answer, citations)
    suppressed = (
        support_rate is not None and support_rate < CITATION_SUPPORT_THRESHOLD
    )
    if suppressed:
        answer = support_gate_message(
            support_rate, CITATION_SUPPORT_THRESHOLD, language
        )
    return answer, citations, support_rate, suppressed


@app.post("/api/v1/auth/register", response_model=AuthResponse)
async def auth_register(payload: AuthRequest) -> AuthResponse:
    try:
        user_id, token, refresh_token, expires_in = register(
            payload.username, payload.password
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AuthResponse(
        token=token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user_id=user_id,
        username=payload.username,
    )


@app.post("/api/v1/auth/login", response_model=AuthResponse)
async def auth_login(payload: AuthRequest) -> AuthResponse:
    result = login(payload.username, payload.password)
    if result is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    user_id, token, refresh_token, expires_in = result
    return AuthResponse(
        token=token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user_id=user_id,
        username=payload.username,
    )


@app.post("/api/v1/auth/refresh", response_model=AuthResponse)
async def auth_refresh(payload: RefreshRequest) -> AuthResponse:
    result = refresh_access(payload.refresh_token)
    if result is None:
        raise HTTPException(status_code=401, detail="刷新令牌已失效，请重新登录")
    user_id, token, refresh_token, expires_in = result
    user = user_from_token(token)
    return AuthResponse(
        token=token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user_id=user_id,
        username=user["username"] if user else "",
    )


@app.get("/api/v1/auth/me")
async def auth_me(user: dict = Depends(require_user)) -> dict:
    return {"user_id": user["id"], "username": user["username"]}


@app.get("/api/v1/collections", response_model=list[CollectionRead])
async def collections(user: dict = Depends(require_user)) -> list[CollectionRead]:
    return [CollectionRead(**item) for item in list_collections(user["id"])]


@app.post("/api/v1/collections", response_model=CollectionRead)
async def new_collection(
    payload: CollectionCreate, user: dict = Depends(require_user)
) -> CollectionRead:
    collection_id = create_collection(user["id"], payload.name)
    item = get_collection(collection_id, user["id"])
    return CollectionRead(**item)


@app.patch("/api/v1/collections/{collection_id}", response_model=CollectionRead)
async def update_collection(
    collection_id: int,
    payload: CollectionCreate,
    user: dict = Depends(require_user),
) -> CollectionRead:
    if get_collection(collection_id, user["id"]) is None:
        raise HTTPException(status_code=404, detail="论文集合不存在")
    rename_collection(collection_id, user["id"], payload.name)
    return CollectionRead(**get_collection(collection_id, user["id"]))


@app.delete("/api/v1/collections/{collection_id}", status_code=204)
async def remove_collection(
    collection_id: int, user: dict = Depends(require_user)
) -> None:
    if get_collection(collection_id, user["id"]) is None:
        raise HTTPException(status_code=404, detail="论文集合不存在")
    try:
        delete_collection(collection_id, user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/v1/papers/{paper_id}/collection", response_model=PaperRead)
async def move_paper_to_collection(
    paper_id: int,
    payload: PaperMove,
    user: dict = Depends(require_user),
) -> PaperRead:
    owned_paper(paper_id, user["id"])
    if get_collection(payload.collection_id, user["id"]) is None:
        raise HTTPException(status_code=404, detail="论文集合不存在")
    move_paper(paper_id, user["id"], payload.collection_id)
    return PaperRead(**owned_paper(paper_id, user["id"]))


@app.post("/api/v1/papers/upload", response_model=UploadResponse, status_code=201)
async def upload_paper(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    collection_id: int | None = Form(default=None),
    user: dict = Depends(require_user),
) -> UploadResponse:
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="只支持 PDF、DOCX、Markdown")

    if collection_id is None:
        collections_list = list_collections(user["id"])
        collection_id = collections_list[0]["id"] if collections_list else None
    elif get_collection(collection_id, user["id"]) is None:
        raise HTTPException(status_code=404, detail="论文集合不存在")

    papers = list_papers(owner_id=user["id"])
    if len(papers) >= MAX_PAPERS:
        raise HTTPException(status_code=400, detail=f"第一版最多支持 {MAX_PAPERS} 篇论文")

    content = await file.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"文件不能超过 {MAX_UPLOAD_MB} MB")
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")

    stored_name = f"{uuid.uuid4().hex}{suffix}"
    stored_path = UPLOAD_DIR / stored_name
    stored_path.write_bytes(content)

    paper_id = create_paper(
        title=Path(filename).stem,
        filename=filename,
        stored_path=str(stored_path),
        file_type=suffix.lstrip("."),
        owner_id=user["id"],
        collection_id=collection_id,
    )
    background_tasks.add_task(
        process_paper,
        paper_id=paper_id,
        path=stored_path,
        file_type=suffix.lstrip("."),
        embedder=app.state.embedder,
        index=app.state.index,
    )
    return UploadResponse(
        paper_id=paper_id,
        status="pending",
        message="已接收，正在后台解析和建立索引。",
    )


@app.get("/api/v1/papers", response_model=list[PaperRead])
async def papers(
    collection_id: int | None = None, user: dict = Depends(require_user)
) -> list[PaperRead]:
    return [
        PaperRead(**paper)
        for paper in list_papers(owner_id=user["id"], collection_id=collection_id)
    ]


@app.get("/api/v1/papers/{paper_id}", response_model=PaperRead)
async def paper(paper_id: int, user: dict = Depends(require_user)) -> PaperRead:
    return PaperRead(**owned_paper(paper_id, user["id"]))


@app.get("/api/v1/papers/{paper_id}/status", response_model=PaperRead)
async def paper_status(paper_id: int, user: dict = Depends(require_user)) -> PaperRead:
    return await paper(paper_id, user)


@app.get("/api/v1/papers/{paper_id}/sections", response_model=list[SectionRead])
async def paper_sections(
    paper_id: int, user: dict = Depends(require_user)
) -> list[SectionRead]:
    owned_paper(paper_id, user["id"])
    return [SectionRead(**section) for section in get_sections(paper_id)]


@app.get("/api/v1/papers/{paper_id}/file", include_in_schema=False)
async def paper_file(paper_id: int, user: dict = Depends(require_user)) -> FileResponse:
    item = owned_paper(paper_id, user["id"])
    path = Path(item["stored_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="原始文件不存在")
    media_types = {
        "pdf": "application/pdf",
        "md": "text/markdown; charset=utf-8",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    return FileResponse(
        path,
        media_type=media_types.get(item["file_type"], "application/octet-stream"),
        filename=item["filename"],
    )


@app.get("/api/v1/papers/{paper_id}/page/{page_number}", include_in_schema=False)
async def paper_page_image(
    paper_id: int,
    page_number: int,
    chunk_id: str | None = None,
    user: dict = Depends(require_user),
) -> Response:
    """Render one PDF page as PNG, optionally highlighting a citation chunk."""
    item = owned_paper(paper_id, user["id"])
    if item["file_type"] != "pdf":
        raise HTTPException(status_code=400, detail="只有 PDF 支持页截图")
    path = Path(item["stored_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="原始文件不存在")

    document = pymupdf.open(path)
    try:
        if page_number < 1 or page_number > len(document):
            raise HTTPException(status_code=404, detail="页码超出范围")
        page = document[page_number - 1]
        if chunk_id:
            chunk = get_chunk(chunk_id)
            if chunk and chunk["paper_id"] == paper_id:
                snippet = " ".join(chunk["content"].split())
                rects = []
                for length in (180, 120, 80, 50):
                    rects = page.search_for(snippet[:length])
                    if rects:
                        break
                for rect in rects:
                    page.add_highlight_annot(rect)
        pixmap = page.get_pixmap(dpi=150)
        return Response(content=pixmap.tobytes("png"), media_type="image/png")
    finally:
        document.close()


@app.post("/api/v1/papers/{paper_id}/reindex", response_model=UploadResponse)
async def reindex_paper(
    paper_id: int,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_user),
) -> UploadResponse:
    item = owned_paper(paper_id, user["id"])
    path = Path(item["stored_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="原始文件不存在，请重新上传")
    app.state.index.delete_paper(paper_id)
    delete_chunks(paper_id)
    update_paper(paper_id, status="pending", error=None, page_count=0, chunk_count=0)
    background_tasks.add_task(
        process_paper,
        paper_id=paper_id,
        path=path,
        file_type=item["file_type"],
        embedder=app.state.embedder,
        index=app.state.index,
    )
    return UploadResponse(
        paper_id=paper_id,
        status="pending",
        message="已提交重新解析。",
    )


@app.delete("/api/v1/papers/{paper_id}", status_code=204)
async def remove_paper(paper_id: int, user: dict = Depends(require_user)) -> None:
    item = owned_paper(paper_id, user["id"])
    app.state.index.delete_paper(paper_id)
    delete_paper(paper_id)
    path = Path(item["stored_path"])
    if path.exists():
        path.unlink()


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, user: dict = Depends(require_user)) -> ChatResponse:
    papers_by_id = {paper_id: get_paper(paper_id) for paper_id in payload.paper_ids}
    missing = [
        paper_id
        for paper_id, item in papers_by_id.items()
        if item is None or item.get("owner_id") != user["id"]
    ]
    if missing:
        raise HTTPException(status_code=404, detail=f"论文不存在: {missing}")
    not_ready = [
        paper_id
        for paper_id, item in papers_by_id.items()
        if item is not None and item["status"] != "ready"
    ]
    if not_ready:
        raise HTTPException(status_code=400, detail=f"论文尚未解析完成: {not_ready}")

    started = time.perf_counter()
    decision = route(payload.question, len(payload.paper_ids), payload.mode)

    if decision.strategy == Strategy.CLARIFY:
        answer = (
            "进行论文对比至少需要选择两篇论文。"
            if payload.answer_language == "zh"
            else "Select at least two papers for a comparison."
        )
        return ChatResponse(
            answer=answer,
            citations=[],
            answer_language=payload.answer_language,
            strategy=decision.strategy.value,
            route_reason=decision.reason,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    if decision.strategy == Strategy.SUMMARY:
        papers_to_summarize = []
        for paper_id in payload.paper_ids[:5]:
            item = papers_by_id[paper_id]
            chunks = get_chunks([paper_id])
            if chunks:
                papers_to_summarize.append({"title": item["title"], "chunks": chunks})
        answer = await summarize_papers(
            papers=papers_to_summarize,
            language=payload.answer_language,
        )
        answer = strip_citation_markers(answer)
        return ChatResponse(
            answer=answer,
            citations=[],
            answer_language=payload.answer_language,
            strategy=decision.strategy.value,
            route_reason=decision.reason,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    if decision.strategy == Strategy.EXPLAIN:
        query_intent = classify_query(payload.question)
        chunks = app.state.retriever.retrieve(
            payload.paper_ids,
            payload.question,
            top_k=5,
            retrieval_query=(
                rewrite_query(payload.question, query_intent)
                if QUERY_REWRITE_ENABLED
                else payload.question
            ),
            sections=(
                query_sections(query_intent) if SECTION_FILTER_ENABLED else None
            ),
        )
        chunks = expand_with_neighbors(chunks)
        entry = lookup(payload.question)
        answer, citations, source_scope, general_used = await answer_explain(
            question=payload.question,
            chunks=chunks,
            glossary_body=entry.body if entry else None,
            language=payload.answer_language,
            allow_general=payload.allow_general_knowledge,
        )
        answer, citations, support_rate, suppressed = await finalize_with_citations(
            answer,
            citations,
            payload.answer_language,
            retriever=app.state.retriever,
        )
        claims, claim_rate = (
            ([], None)
            if suppressed
            else build_claim_checks(answer, citations)
        )
        return ChatResponse(
            answer=answer,
            citations=citations,
            answer_language=payload.answer_language,
            strategy=decision.strategy.value,
            route_reason=decision.reason,
            source_scope=source_scope,
            general_knowledge_used=general_used,
            citation_support_rate=support_rate,
            citation_support_threshold=CITATION_SUPPORT_THRESHOLD,
            answer_suppressed=suppressed,
            claims=claims,
            claim_support_rate=claim_rate,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    if decision.strategy == Strategy.COMPARE:
        chunks = app.state.retriever.retrieve_balanced(
            payload.paper_ids, payload.question, per_paper=3
        )
        chunks = expand_with_neighbors(chunks)
        answer, citations = await answer_compare(
            question=payload.question,
            chunks=chunks,
            language=payload.answer_language,
        )
    elif decision.strategy == Strategy.INNOVATE:
        query = f"{payload.question} limitations future work research gap"
        chunks = app.state.retriever.retrieve_balanced(
            payload.paper_ids, query, per_paper=3
        )
        chunks = expand_with_neighbors(chunks)
        answer, citations = await answer_innovation(
            question=payload.question,
            chunks=chunks,
            language=payload.answer_language,
        )
    else:
        query_intent = classify_query(payload.question)
        chunks = app.state.retriever.retrieve(
            payload.paper_ids,
            payload.question,
            top_k=6,
            retrieval_query=(
                rewrite_query(payload.question, query_intent)
                if QUERY_REWRITE_ENABLED
                else payload.question
            ),
            sections=(
                query_sections(query_intent) if SECTION_FILTER_ENABLED else None
            ),
        )
        chunks = expand_with_neighbors(chunks)
        answer, citations = await generate_answer(
            question=payload.question,
            chunks=chunks,
            language=payload.answer_language,
        )

    answer, citations, support_rate, suppressed = await finalize_with_citations(
        answer,
        citations,
        payload.answer_language,
        retriever=app.state.retriever,
    )
    claims, claim_rate = (
        ([], None)
        if suppressed
        else build_claim_checks(answer, citations)
    )
    return ChatResponse(
        answer=answer,
        citations=citations,
        answer_language=payload.answer_language,
        strategy=decision.strategy.value,
        route_reason=decision.reason,
        citation_support_rate=support_rate,
        citation_support_threshold=CITATION_SUPPORT_THRESHOLD,
        answer_suppressed=suppressed,
        claims=claims,
        claim_support_rate=claim_rate,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
    )


@app.post("/api/v1/chat/stream")
async def chat_stream(payload: ChatRequest, user: dict = Depends(require_user)):
    papers_by_id = {paper_id: get_paper(paper_id) for paper_id in payload.paper_ids}
    if any(
        item is None or item.get("owner_id") != user["id"]
        for item in papers_by_id.values()
    ):
        raise HTTPException(status_code=404, detail="论文不存在")
    if any(item["status"] != "ready" for item in papers_by_id.values()):
        raise HTTPException(status_code=400, detail="论文尚未解析完成")

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    async def events():
        started = time.perf_counter()
        decision = route(payload.question, len(payload.paper_ids), payload.mode)
        yield sse(
            "route",
            {"strategy": decision.strategy.value, "reason": decision.reason},
        )

        if decision.strategy == Strategy.CLARIFY:
            text = (
                "进行论文对比至少需要选择两篇论文。"
                if payload.answer_language == "zh"
                else "Select at least two papers for a comparison."
            )
            yield sse("token", {"text": text})
            yield sse(
                "final",
                {
                    "answer": text,
                    "citations": [],
                    "strategy": decision.strategy.value,
                    "route_reason": decision.reason,
                    "source_scope": "paper",
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            return

        if decision.strategy == Strategy.SUMMARY:
            papers_to_summarize = []
            for paper_id in payload.paper_ids[:5]:
                item = papers_by_id[paper_id]
                chunks = get_chunks([paper_id])
                if chunks:
                    papers_to_summarize.append(
                        {"title": item["title"], "chunks": chunks}
                    )
            answer = await summarize_papers(
                papers=papers_to_summarize, language=payload.answer_language
            )
            answer = strip_citation_markers(answer)
            for index in range(0, len(answer), 48):
                yield sse("token", {"text": answer[index : index + 48]})
            yield sse(
                "final",
                {
                    "answer": answer,
                    "citations": [],
                    "strategy": decision.strategy.value,
                    "route_reason": decision.reason,
                    "source_scope": "paper",
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            return

        if decision.strategy == Strategy.COMPARE:
            chunks = app.state.retriever.retrieve_balanced(
                payload.paper_ids, payload.question, per_paper=3
            )
            source_scope = "paper"
        elif decision.strategy == Strategy.INNOVATE:
            chunks = app.state.retriever.retrieve_balanced(
                payload.paper_ids,
                f"{payload.question} limitations future work research gap",
                per_paper=3,
            )
            source_scope = "paper"
        elif decision.strategy == Strategy.EXPLAIN:
            query_intent = classify_query(payload.question)
            chunks = app.state.retriever.retrieve(
                payload.paper_ids,
                payload.question,
                top_k=5,
                retrieval_query=(
                    rewrite_query(payload.question, query_intent)
                    if QUERY_REWRITE_ENABLED
                    else payload.question
                ),
                sections=(
                    query_sections(query_intent) if SECTION_FILTER_ENABLED else None
                ),
            )
            entry = lookup(payload.question)
            source_scope = "paper+glossary" if entry else "paper"
        else:
            query_intent = classify_query(payload.question)
            chunks = app.state.retriever.retrieve(
                payload.paper_ids,
                payload.question,
                top_k=6,
                retrieval_query=(
                    rewrite_query(payload.question, query_intent)
                    if QUERY_REWRITE_ENABLED
                    else payload.question
                ),
                sections=(
                    query_sections(query_intent) if SECTION_FILTER_ENABLED else None
                ),
            )
            source_scope = "paper"

        chunks = expand_with_neighbors(chunks)
        entry = lookup(payload.question) if decision.strategy == Strategy.EXPLAIN else None
        prompt = build_stream_prompt(
            decision.strategy.value,
            question=payload.question,
            chunks=chunks,
            language=payload.answer_language,
            glossary_body=entry.body if entry else None,
            allow_general=payload.allow_general_knowledge,
        )

        answer = ""
        try:
            async for delta in stream_complete(prompt, max_tokens=1800):
                answer += delta
                yield sse("token", {"text": delta})
        except Exception as exc:
            yield sse("error", {"detail": str(exc)})
            return

        citations = _citations_from_answer(answer, chunks)
        final_answer, ordered = _renumber_citations(answer, citations)
        final_answer, ordered, support_rate, suppressed = await finalize_with_citations(
            final_answer,
            ordered,
            payload.answer_language,
            retriever=app.state.retriever,
        )
        claims, claim_rate = (
            ([], None)
            if suppressed
            else build_claim_checks(final_answer, ordered)
        )
        yield sse(
            "final",
            {
                "answer": final_answer,
                "citations": [citation.model_dump() for citation in ordered],
                "claims": [claim.model_dump() for claim in claims],
                "strategy": decision.strategy.value,
                "route_reason": decision.reason,
                "source_scope": source_scope,
                "citation_support_rate": support_rate,
                "citation_support_threshold": CITATION_SUPPORT_THRESHOLD,
                "answer_suppressed": suppressed,
                "claim_support_rate": claim_rate,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/v1/summarize", response_model=SummaryResponse)
async def summarize(
    payload: SummaryRequest, user: dict = Depends(require_user)
) -> SummaryResponse:
    papers_to_summarize = []
    for paper_id in payload.paper_ids:
        item = get_paper(paper_id)
        if item is None or item.get("owner_id") != user["id"]:
            raise HTTPException(status_code=404, detail=f"论文不存在: {paper_id}")
        if item["status"] != "ready":
            raise HTTPException(status_code=400, detail=f"论文尚未解析完成: {paper_id}")
        chunks = get_chunks([paper_id])
        if not chunks:
            raise HTTPException(status_code=400, detail=f"论文没有可用文本: {paper_id}")
        papers_to_summarize.append({"title": item["title"], "chunks": chunks})

    started = time.perf_counter()
    summary = await summarize_papers(
        papers=papers_to_summarize,
        language=payload.answer_language,
    )
    summary = strip_citation_markers(summary)
    return SummaryResponse(
        summary=summary,
        answer_language=payload.answer_language,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
    )


# Serve the production React build from the same FastAPI origin.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend_react" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
