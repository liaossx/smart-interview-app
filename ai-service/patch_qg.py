import sys

with open('app/agents/question_generator.py', 'rb') as f:
    raw = f.read()

import_start = raw.find(b'from langchain.agents import create_agent')
import_json_end = raw.find(b'import json\n', import_start) + len(b'import json\n')
node_pos = raw.find(b'def question_generator_node')

new_imports = (
    b'from langchain.agents import create_agent\n'
    b'from langchain_core.messages import HumanMessage\n'
    b'from app.core.llm import get_creative_llm\n'
    b'from app.agents.state import InterviewState\n'
    b'from app.core.rag_engine import retrieve_resume_context\n'
    b'import json\n'
    b'import logging\n'
    b'\n'
    b'logger = logging.getLogger(__name__)\n'
)

new_node_func = b'''def question_generator_node(state: InterviewState) -> InterviewState:
    """
    RAG-enhanced question generator node.

    Adds RAG context injection before question generation:
    1. Extracts JD focus topics (tech_stack + missing_skills + common backend topics)
    2. Queries the session Chroma vector DB for matching resume project snippets
    3. Injects retrieved snippets into the prompt for targeted project deep-dive questions
    4. Falls back gracefully if no RAG data is available
    """
    session_id = state.get("session_id", "")

    # RAG: retrieve relevant resume context for project deep-dive questions
    rag_context_lines = []
    try:
        jd_analysis = state.get("jd_analysis", {})
        gap_analysis = state.get("gap_analysis", {})

        query_topics = []
        tech_stack = jd_analysis.get("tech_stack", [])
        if isinstance(tech_stack, list):
            query_topics.extend(tech_stack[:4])
        missing_skills = gap_analysis.get("missing_skills", [])
        if isinstance(missing_skills, list):
            query_topics.extend(missing_skills[:3])
        query_topics.extend(["\xe9\xab\x98\xe5\xb9\xb6\xe5\x8f\x91", "\xe5\x88\x86\xe5\xb8\x83\xe5\xbc\x8f", "\xe7\xbc\x93\xe5\xad\x98"])

        seen = set()
        unique_topics = [t for t in query_topics if t and t not in seen and not seen.add(t)]

        for topic in unique_topics[:6]:
            snippet = retrieve_resume_context(session_id, topic, top_k=1, min_similarity=0.35)
            if snippet:
                rag_context_lines.append(f"[\\xe8\\x80\\x83\\xe7\\x82\\xb9: {topic}]\\n{snippet}")

    except Exception as e:
        logger.warning(f"Session {session_id}: RAG retrieval failed ({e}), using fallback mode")

    jd_json = json.dumps(state.get("jd_analysis", {}), ensure_ascii=False, indent=2)
    resume_json = json.dumps(state.get("resume_analysis", {}), ensure_ascii=False, indent=2)
    gap_json = json.dumps(state.get("gap_analysis", {}), ensure_ascii=False, indent=2)

    input_text = f"JD \\xe5\\x88\\x86\\xe6\\x9e\\x90: {jd_json}\\n\\n\\xe7\\xae\\x80\\xe5\\x8e\\x86\\xe5\\x88\\x86\\xe6\\x9e\\x90: {resume_json}\\n\\n\\xe5\\xb7\\xae\\xe8\\xb7\\x9d\\xe5\\x88\\x86\\xe6\\x9e\\x90: {gap_json}\\n"

    if rag_context_lines:
        rag_block = "\\n\\n".join(rag_context_lines)
        rag_note = (
            "\\n\\n[RAG \\xe7\\xae\\x80\\xe5\\x8e\\x86\\xe8\\xaf\\xad\\xe4\\xb9\\x89\\xe6\\xa3\\x80\\xe7\\xb4\\xa2\\xe7\\xbb\\x93\\xe6\\x9e\\x9c -- \\xe9\\xa1\\xb9\\xe7\\x9b\\xae\\xe6\\xb7\\xb1\\xe6\\x8c\\x96\\xe5\\x8f\\x82\\xe8\\x80\\x83]\\n"
            "\\xe4\\xbb\\xa5\\xe4\\xb8\\x8b\\xe6\\x98\\xaf\\xe4\\xbb\\x8e\\xe5\\x80\\x99\\xe9\\x80\\x89\\xe4\\xba\\xba\\xe7\\xae\\x80\\xe5\\x8e\\x86\\xe8\\xaf\\xad\\xe4\\xb9\\x89\\xe6\\xa3\\x80\\xe7\\xb4\\xa2\\xe5\\x88\\xb0\\xe7\\x9a\\x84\\xe6\\x9c\\x80\\xe7\\x9b\\xb8\\xe5\\x85\\xb3\\xe9\\xa1\\xb9\\xe7\\x9b\\xae\\xe7\\x89\\x87\\xe6\\xae\\xb5\\xef\\xbc\\x8c\\xe5\\x9c\\xa8\\xe7\\x94\\x9f\\xe6\\x88\\x90\\xe9\\xa1\\xb9\\xe7\\x9b\\xae\\xe6\\xb7\\xb1\\xe6\\x8c\\x96\\xe9\\xa2\\x98\\xe6\\x97\\xb6\\xe5\\xbf\\x85\\xe9\\xa1\\xbb\\xe5\\x8f\\x82\\xe8\\x80\\x83\\xe8\\xbf\\x99\\xe4\\xba\\x9b\\xe7\\x9c\\x9f\\xe5\\xae\\x9e\\xe9\\xa1\\xb9\\xe7\\x9b\\xae\\xe4\\xb8\\xad\\xe7\\x9a\\x84\\xe5\\x85\\xb7\\xe4\\xbd\\x93\\xe6\\x8a\\x80\\xe6\\x9c\\xaf\\xe7\\xbb\\x86\\xe8\\x8a\\x82\\xe8\\xbf\\x9b\\xe8\\xa1\\x8c\\xe5\\xae\\x9a\\xe5\\x88\\xb6\\xe5\\x8c\\x96\\xe6\\xb7\\xb1\\xe6\\x8c\\x96\\xe9\\x97\\xae\\xe9\\xa2\\x98\\xef\\xbc\\x9a\\n\\n"
        )
        input_text += rag_note + rag_block
        logger.info(f"Session {session_id}: RAG injected {len(rag_context_lines)} snippets into prompt")
    else:
        logger.info(f"Session {session_id}: No RAG context, using standard mode")

    agent = _get_question_generator()
    result = agent.invoke({"messages": [HumanMessage(content=input_text)]})

    try:
        data = json.loads(result["messages"][-1].content)
        questions = data.get("questions", [])
    except (json.JSONDecodeError, KeyError):
        questions = []

    return {
        **state,
        "questions": questions,
        "current_question_index": 0,
        "phase": "questions_ready",
    }
'''

preserved_head = raw[:import_start]
between = raw[import_json_end:node_pos]
final = preserved_head + new_imports + between + new_node_func

with open('app/agents/question_generator.py', 'wb') as f:
    f.write(final)

print('Done! size:', len(final))
print('RAG import OK:', b'from app.core.rag_engine import retrieve_resume_context' in final)
print('node func OK:', b'def question_generator_node' in final)
print('logger OK:', b'logger = logging.getLogger' in final)
