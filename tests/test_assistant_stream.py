"""The chat endpoint end to end with a stand-in model: routing, tool events,
the grounded prompt, the streamed reply and its saving, under both routers.

The embedding model is replaced too (no semantic search, neutral tone), so
the test needs neither the LLM nor sentence-transformers.
"""
import json
from datetime import date, timedelta

import pytest

from app.modules.assistant import routes


class FakeLLM:
    """Plays each role the chat asks of the model, and remembers the prompts."""

    def __init__(self):
        self.calls = []

    def tokenize(self, data: bytes):
        return list(range(max(1, len(data) // 4)))

    def create_chat_completion(self, **kw):
        self.calls.append(kw)
        prompt = kw['messages'][0]['content']
        if kw.get('response_format'):             # scenario router
            return {'choices': [{'message': {'content': json.dumps(
                {'scenario': 'person', 'topic': '', 'person': 'Маша'})}}]}
        if prompt.startswith('Ты — маршрутизатор'):  # old router
            return {'choices': [{'message': {'content': json.dumps(
                [{'tool': 'person_history', 'args': {'name': 'Маша'}}])}}]}
        assert kw.get('stream') is True
        return iter([{'choices': [{'delta': {'content': 'Судя по записям, '}}]},
                     {'choices': [{'delta': {'content': 'с Машей тебе хорошо.'}}]}])


@pytest.fixture
def chat(app, monkeypatch):
    from app import db
    from app.models import EntryPerson, MoodEntry
    from app.modules.assistant import bp, memory, tools

    app.register_blueprint(bp, url_prefix='/assistant')
    today = date.today()
    for i in range(10):
        e = MoodEntry(date=today - timedelta(days=i), rating=6 + i % 3,
                      note=f'Гуляли с Машей, день {i}.', deleted=False)
        db.session.add(e)
        db.session.flush()
        db.session.add(EntryPerson(entry_id=e.id, mention='Маша', tone='positive'))
    db.session.commit()

    llm = FakeLLM()
    monkeypatch.setattr(routes, '_get_llm', lambda: llm)
    monkeypatch.setattr(memory, 'search_relevant_entries', lambda *a, **k: [])
    monkeypatch.setattr(tools, 'search_relevant_entries', lambda *a, **k: [])
    monkeypatch.setattr(memory, 'detect_emotional_tone', lambda text: ('neutral', 0.0))
    return app.test_client(), llm


def _events(resp):
    out = []
    for block in resp.get_data(as_text=True).split('\n\n'):
        if block.startswith('data: ') and block != 'data: [DONE]':
            out.append(json.loads(block[6:]))
    return out


@pytest.mark.parametrize('mode, tool', [('scenario', 'person_deep'), ('legacy', 'person_history')])
def test_a_question_is_routed_grounded_streamed_and_saved(chat, monkeypatch, mode, tool):
    from app.models import ChatMessage
    client, llm = chat
    monkeypatch.setenv('ASSISTANT_ROUTER', mode)
    resp = client.post('/assistant/stream', json={'message': 'Что я писал про Машу?'})
    events = _events(resp)

    tools_called = [e['tool'] for e in events if 'tool' in e]
    assert tools_called == [tool]
    assert {'tool_done': True} in events
    assert ''.join(e.get('token', '') for e in events) == 'Судя по записям, с Машей тебе хорошо.'

    # The reply was generated from a prompt holding the tool's evidence.
    final = llm.calls[-1]
    system = final['messages'][0]['content']
    assert f'[{tool}]' in system and 'Маша' in system
    assert final['messages'][-1] == {'role': 'user', 'content': 'Что я писал про Машу?'}

    saved = ChatMessage.query.order_by(ChatMessage.id).all()
    assert [(m.role, m.content) for m in saved] == [
        ('user', 'Что я писал про Машу?'),
        ('assistant', 'Судя по записям, с Машей тебе хорошо.')]


def test_the_scenario_path_leaves_out_the_layers_its_tools_repeat(chat, monkeypatch):
    client, llm = chat
    monkeypatch.setenv('ASSISTANT_ROUTER', 'scenario')
    seen = {}
    real = __import__('app.modules.assistant.memory', fromlist=['assemble_context']).assemble_context

    def spy(message, max_system_tokens=0, **layers):
        seen.update(layers)
        return real(message, max_system_tokens, **layers)
    monkeypatch.setattr('app.modules.assistant.memory.assemble_context', spy)
    client.post('/assistant/stream', json={'message': 'Что я писал про Машу?'}).get_data()
    assert seen == {'relevant': False, 'timeline': False}


def test_routing_runs_with_thinking_off_even_when_the_reply_thinks(chat, monkeypatch):
    client, llm = chat
    monkeypatch.setenv('ASSISTANT_ROUTER', 'scenario')
    states = []
    real = llm.create_chat_completion

    def record(**kw):
        states.append(routes._get_request_thinking())
        return real(**kw)
    llm.create_chat_completion = record
    client.post('/assistant/stream', json={'message': 'Что я писал про Машу?',
                                           'enable_thinking': True}).get_data()
    assert states[0] is False   # the router
    assert states[1] is True    # the reply (a "final answer only" retry may follow)
