"""Evidence-grounded query orchestration and replaceable Ollama chat adapter."""
from __future__ import annotations

import json
import os
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from query_classifier import classify_query
from structural_query import answer_structural_query


class OllamaChatClient:
    def __init__(self, base_url=None, model=None, timeout=None):
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
        self.timeout = float(timeout or os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))

    def generate(self, prompt: str) -> str:
        payload = json.dumps({"model": self.model, "stream": False, "messages": [
            {"role": "system", "content": "Answer only from supplied evidence. If it does not support an answer, say so. Do not add citations or source locations."},
            {"role": "user", "content": prompt},
        ]}).encode("utf-8")
        request = Request(self.base_url + "/api/chat", data=payload,
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            return result["message"]["content"]
        except (HTTPError, URLError, TimeoutError, KeyError, ValueError) as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc


def _citation(repo_id, revision, file, start, end, source_type):
    return {"repository_id": str(repo_id), "revision": str(revision) if revision else None,
            "file_path": file, "start_line": int(start), "end_line": int(end),
            "source_type": source_type}


def answer_query(repo_id, revision, question, graph, search_fn, llm_client,
                 limit=5):
    classification = classify_query(question)
    chunks, structural = [], None
    if "semantic" in classification["routes"]:
        chunks = search_fn(repo_id, question, limit=limit)
    if "structural" in classification["routes"] and graph is not None:
        if graph.repo_id != str(repo_id) or (revision and graph.revision != str(revision)):
            raise ValueError("Symbol graph repository or revision does not match query")
        structural = answer_structural_query(graph, question)

    citations, evidence = [], []
    for chunk in chunks:
        file = chunk.get("file_path", chunk.get("file"))
        start, end = chunk.get("start_line"), chunk.get("end_line")
        source = chunk.get("source")
        if file and start is not None and end is not None and source is not None:
            chunk_revision = chunk.get("revision")
            if revision and chunk_revision and str(chunk_revision) != str(revision):
                raise ValueError("Retrieved chunk revision does not match requested revision")
            citation = _citation(repo_id, revision or chunk_revision, file, start, end, "chunk")
            citations.append(citation)
            evidence.append({"citation": citation, "source": source})
    if structural:
        for item in structural["evidence"]:
            start = item.get("start_line", item.get("line"))
            end = item.get("end_line", item.get("line"))
            citation = _citation(repo_id, graph.revision, item["file"], start, end, "symbol_graph")
            citations.append(citation)
            evidence.append({"citation": citation, "relationship": item["relationship"],
                             "symbol": item.get("symbol"), "caller": item.get("caller")})
    if not evidence:
        return {"repo_id": str(repo_id), "revision": revision, "classification": classification,
                "answer": "I could not find sufficient indexed evidence to answer this question.",
                "citations": [], "status": "insufficient_evidence"}

    sections = []
    for index, item in enumerate(evidence, 1):
        sections.append(f"[{index}] {json.dumps(item, ensure_ascii=False)}")
    prompt = ("Answer the question using only the evidence below. Explain uncertainty when needed. "
              "Do not create source references.\nQuestion: " + question +
              "\nEvidence:\n" + "\n".join(sections))
    try:
        answer = llm_client.generate(prompt)
    except Exception as exc:
        raise RuntimeError(f"Answer synthesis failed: {exc}") from exc
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("Answer synthesis failed: model returned an empty answer")
    return {"repo_id": str(repo_id), "revision": revision, "classification": classification,
            "answer": answer.strip(), "citations": citations, "status": "answered",
            "structural_status": structural["status"] if structural else None}
