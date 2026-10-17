import httpx
from fastapi.testclient import TestClient
import src.main as m
from src.main import app
import json


c = TestClient(app)
ok = {'action': "chat", "book_id": "b", "section_id": "s", "instructions": "hola mundo"}

def test_book_id_vacio():
    r = c.post("/execute", json={**ok, "book_id": " "})
    assert r.status_code == 422 and r.json()["fields"] == ["book_id"]

def test_action_no_soportada():
    r = c.post("/execute", json={**ok, "action": "otro"})
    assert r.status_code == 422 and r.json()["fields"] == ["action"]

def fake(status, body):
    return lambda *a, **k: httpx.Response(status, json=body)

def test_contexto_vacio(monkeypatch):
    monkeypatch.setattr(httpx, "post", fake(200, {"title": " t", "content": ""}))
    r = c.post("/execute", json=ok)
    assert r.status_code == 422 and r.json()["code"] == "EMPTY_CONTENT"

def test_libro_inexistente(monkeypatch):
    monkeypatch.setattr(httpx, "post", fake(404, {"error": {"code": "BOOK_NOT_FOUND", "message": "x"}}))
    r = c.post("/execute", json=ok)
    assert r.status_code == 404 and r.json()["code"] == "BOOK_NOT_FOUND"


def test_contexto_caido(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectTimeout("x")
    monkeypatch.setattr(httpx, "post", boom)
    r = c.post("/execute", json=ok)
    assert r.status_code == 504 and r.json()["code"] == "CONTEXT_UNAVAILABLE"


def ctx_ok(monkeypatch):
    monkeypatch.setattr(httpx, "post", fake(200, {"title": "t", "content": "La mitosis produce dos células."}))


def test_chat_ok(monkeypatch):
    ctx_ok(monkeypatch)
    seen = {}

    def spy(system, user):
        seen["s"], seen["u"] = system, user
        return '{"status": "ok", "result": {"answer": "Dos células."}}'

    monkeypatch.setattr(m, "call_llm", spy)
    r = c.post("/execute", json=ok)
    assert r.json() == {"action": "chat", "answer": "Dos células.", "warnings": []}
    assert "mitosis" not in seen["s"] and "<contenido>" in seen["u"]  # contenido fuera del system


def test_chat_no_esta_en_contenido(monkeypatch):
    ctx_ok(monkeypatch)
    monkeypatch.setattr(m, "call_llm", lambda s, u: 
                        '{"status": "not_in_content", "message":"No aparece."}')
    r = c.post("/execute", json=ok)
    assert r.status_code == 422 and r.json()["code"] == "NOT_IN_CONTENT"


def test_chat_respuesta_invalida(monkeypatch):
    ctx_ok(monkeypatch)
    monkeypatch.setattr(m, "call_llm", lambda s, u: "no es json")
    r = c.post("/execute", json=ok)
    assert r.status_code == 504 and r.json()["code"] == "INVALID_AI_RESPONSE"

QUIZ = {"title": "T", "instructions": "Elige una.", "questions": [
    {"question": "¿Cuántas células produce la mitosis?", "options": ["1", "2", "3", "4"],
     "correct_answer": "2", "explanation": "Produce dos células."}]}


def llm_returns(monkeypatch, body):
    monkeypatch.setattr(m, "call_llm", lambda s, u: json.dumps(body))


def test_quiz_ok_con_valor_por_defecto(monkeypatch):
    ctx_ok(monkeypatch)
    llm_returns(monkeypatch, {"status": "ok", "warnings": ["Se usaron 1 preguntas."], "result": QUIZ})
    r = c.post("/execute", json={**ok, "action": "quiz"})
    assert r.status_code == 200 and r.json() == {"action": "quiz", **QUIZ, "warnings": ["Se usaron 1 preguntas."]}


def test_quiz_respuesta_fuera_de_opciones(monkeypatch):
    ctx_ok(monkeypatch)
    q = {**QUIZ["questions"][0], "correct_answer": "5"}
    llm_returns(monkeypatch, {"status": "ok", "result": {**QUIZ, "questions": [q]}})
    r = c.post("/execute", json={**ok, "action": "quiz"})
    assert r.status_code == 504 and r.json()["code"] == "INVALID_AI_RESPONSE"


def test_activity_ok_sin_result(monkeypatch):
    ctx_ok(monkeypatch)
    llm_returns(monkeypatch, {"status": "ok", "result": None})
    r = c.post("/execute", json={**ok, "action": "activity"})
    assert r.status_code == 504 and r.json()["code"] == "INVALID_AI_RESPONSE"


def test_pide_aclaracion(monkeypatch):
    ctx_ok(monkeypatch)
    llm_returns(monkeypatch, {"status": "needs_clarification", "message": "¿Fácil o difícil?"})
    r = c.post("/execute", json={**ok, "action": "activity"})
    assert r.status_code == 422 and r.json() == {
        "status": "error", "code": "NEEDS_CLARIFICATION", "message": "¿Fácil o difícil?"}


def test_json_malformado_señala_body():
    r = c.post("/execute", content='{"action": "chat",', headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["fields"] == ["body"]


def test_contexto_con_forma_inesperada(monkeypatch):
    for status, body in [(200, {"content": None}), (200, ["x"]), (404, {"error": "x"}), (404, {"error": {"code": "OTRO"}})]:
        monkeypatch.setattr(httpx, "post", fake(status, body))
        r = c.post("/execute", json=ok)
        assert r.status_code == 504 and r.json()["code"] == "CONTEXT_ERROR", (status, body)


def test_no_revela_el_prompt(monkeypatch):
    ctx_ok(monkeypatch)
    llm_returns(monkeypatch, {"status": "ok", "result": {"answer": m.RULES}})
    r = c.post("/execute", json=ok)
    assert r.status_code == 422 and r.json()["code"] == "NOT_IN_CONTENT"
