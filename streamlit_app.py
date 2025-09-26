import os
import streamlit as st
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores import FAISS
from langchain.chat_models import ChatOpenAI
from langchain.document_loaders import PyPDFLoader
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.tools.retriever import create_retriever_tool
from langchain.prompts import ChatPromptTemplate
import tempfile
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_community.utilities import SerpAPIWrapper
from langchain.agents import Tool

# .env 파일 로드
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# ✅ SerpAPI 검색 툴 정의
def search_web():
    search = SerpAPIWrapper()
    
    def run_with_source(query: str) -> str:
        results = search.results(query)
        organic = results.get("organic_results", [])
        formatted = []
        for r in organic[:5]:
            title = r.get("title")
            link = r.get("link")
            source = r.get("source")
            snippet = r.get("snippet")  # ✅ snippet 추가
            if link:
                formatted.append(f"- [{title}]({link}) ({source})\n  {snippet}")
            else:
                formatted.append(f"- {title} (출처: {source})\n  {snippet}")
        return "\n".join(formatted) if formatted else "검색 결과가 없습니다."
    
    return Tool(
        name="web_search",
        func=run_with_source,
        description="Use it to search for real-time news and web information. Results are returned in the format of title + source + link + brief summary (snippet)."
    )

# ✅ PDF 업로드 → 벡터DB → 검색 툴 생성
def load_pdf_files(uploaded_files):
    all_documents = []
    for uploaded_file in uploaded_files:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.read())
            tmp_file_path = tmp_file.name

        loader = PyPDFLoader(tmp_file_path)
        documents = loader.load()
        all_documents.extend(documents)

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    split_docs = text_splitter.split_documents(all_documents)

    vector = FAISS.from_documents(split_docs, OpenAIEmbeddings())
    retriever = vector.as_retriever()

    retriever_tool = create_retriever_tool(
        retriever,
        name="pdf_search",
        description="Use this tool to search information from the pdf document"
    )
    return retriever_tool

# ✅ Agent 대화 실행
def chat_with_agent(user_input, agent_executor):
    result = agent_executor({"input": user_input})
    return result['output']

# ✅ 세션별 히스토리 관리
def get_session_history(session_ids):
    if session_ids not in st.session_state.session_history:
        st.session_state.session_history[session_ids] = ChatMessageHistory()
    return st.session_state.session_history[session_ids]

# ✅ 이전 메시지 출력
def print_messages():
    for msg in st.session_state["messages"]:
        st.chat_message(msg['role']).write(msg['content'])

# ✅ 메인 실행
def main():
    st.set_page_config(page_title="DIPA", layout="wide", page_icon="🥗")

    with st.container():
        st.image('./logo.png', use_container_width=True)
        st.markdown('---')
        st.title("안녕하세요! RAG를 활용한 식단 추천 AI'DIPA' 입니다")

    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    if "session_history" not in st.session_state:
        st.session_state["session_history"] = {}

    with st.sidebar:
        st.session_state["OPENAI_API"] = st.text_input("OPENAI API 키", placeholder="Enter Your API Key", type="password")
        st.session_state["SERPAPI_API"] = st.text_input("SERPAPI_API 키", placeholder="Enter Your API Key", type="password")
        st.markdown('---')
        pdf_docs = st.file_uploader("Upload your PDF Files", accept_multiple_files=True, key="pdf_uploader")

        # ✅ 새로고침 버튼 추가
        if st.button("🔄 새로고침 / 대화 초기화"):
            st.session_state["messages"] = []
            st.session_state["session_history"] = {}
            st.rerun()  # 화면 전체 새로고침
    
    # ✅ 키 입력 확인
    if st.session_state["OPENAI_API"] and st.session_state["SERPAPI_API"]:
        os.environ['OPENAI_API_KEY'] = st.session_state["OPENAI_API"]
        os.environ['SERPAPI_API_KEY'] = st.session_state["SERPAPI_API"]

        # 도구 정의
        tools = []
        if pdf_docs:
            pdf_search = load_pdf_files(pdf_docs)
            tools.append(pdf_search)
        tools.append(search_web())

        # LLM 설정
        llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0)

        prompt = ChatPromptTemplate.from_messages(
            [
            ("system",
            "Be sure to answer in Korean. You are a helpful assistant. "
            "You are DIPA, a friendly and professional diet recommendation AI. "
            "You must provide optimized diet recommendations based on the user's situation. "
            "** IMPORTANT RULE: If the user does not provide specific details (such as health condition, allergies, dietary goals, exercise habits, or preferred foods),"
            "you MUST ask at least 1 clarifying questions before giving any diet recommendations. "
            "Do not skip this step. Asking clarifying questions first is REQUIRED. "
            "When you provide a diet recommendation, you MUST include the reasoning or evidence behind each recommendation "
            "(e.g., 'Includes chicken breast for protein balance', 'I cut down on carbohydrates in the morning to control calories.'). "
            "Be sure to use the `pdf_search` tool to retrieve information from the PDF document. "
            "If you cannot find the information in the PDF, use the `web_search` tool. "
            "If the user’s question includes words like '최신', '현재', or '오늘', you must ALWAYS use the `web_search` tool to ensure real-time information is retrieved. "
            "If the user asks a question unrelated to diets, you must politely respond that you only answer diet-related questions. "
            "Always answer with a friendly tone and include emojis in your responses."
            "If possible, please include the recipe and the source site for the recipe."
            ),
            ("placeholder", "{chat_history}"),
            ("human", "{input} \n\n Please be sure to include emojis in your responses."),
            ("placeholder", "{agent_scratchpad}"),

            ]
        )


        agent = create_tool_calling_agent(llm, tools, prompt)
        agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

        # 입력창
        user_input = st.chat_input('질문이 무엇인가요?')

        if user_input:
            session_id = "default_session"
            session_history = get_session_history(session_id)

            if session_history.messages:
                prev_msgs = [{"role": msg['role'], "content": msg['content']} for msg in session_history.messages]
                response = chat_with_agent(user_input + "\n\nPrevious Messages: " + str(prev_msgs), agent_executor)
            else:
                response = chat_with_agent(user_input, agent_executor)

            st.session_state["messages"].append({"role": "user", "content": user_input})
            st.session_state["messages"].append({"role": "assistant", "content": response})

            session_history.add_message({"role": "user", "content": user_input})
            session_history.add_message({"role": "assistant", "content": response})

        print_messages()

    else:
        st.warning("OpenAI API 키와 SerpAPI API 키를 입력하세요.")

if __name__ == "__main__":
    main()
