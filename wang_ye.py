import json
import random
import re
from typing import List, Dict, Any

import streamlit as st
from pptx import Presentation  # 处理 PPT
import pdfplumber              # 处理 PDF (记得 pip install pdfplumber)
from openai import OpenAI      # 处理 AI

# ==========================================
# 🔧 配置区域
# ==========================================

# ⚠️ 必须修改：在这里填入你的真实 Key
try:
    DEEPSEEK_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
except:
    # ↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓
    DEEPSEEK_API_KEY = "sk-在这里填入你的真实Key" 
    # ↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑

# 如果用 SiliconFlow，改成 "https://api.siliconflow.cn/v1"
BASE_URL = "https://api.deepseek.com" 

# ==========================================
# 1. 核心工具函数区 (新增了 PDF 处理)
# ==========================================

def extract_text_from_pptx(uploaded_file):
    """从上传的PPT文件中提取所有文本"""
    try:
        prs = Presentation(uploaded_file)
        full_text = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    full_text.append(shape.text.strip())
        return "\n".join(full_text)
    except Exception as e:
        st.error(f"解析PPT失败: {e}")
        return ""

def extract_text_from_pdf(uploaded_file):
    """从上传的PDF文件中提取所有文本 (新功能)"""
    try:
        text_content = []
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_content.append(text)
        return "\n".join(text_content)
    except Exception as e:
        st.error(f"解析PDF失败: {e}")
        return ""

def normalize_text(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s

def simple_keywords(text: str, topn: int = 6) -> List[str]:
    candidates = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", text)
    freq = {}
    for c in candidates:
        freq[c] = freq.get(c, 0) + 1
    items = sorted(freq.items(), key=lambda x: (-x[1], -len(x[0])))
    return [w for w, _ in items[:topn]]

# ==========================================
# 2. 真正的 AI 生成逻辑 (DeepSeek)
# ==========================================

@st.cache_data(show_spinner=False)
def call_deepseek_generate(content: str, difficulty: str, style: str) -> Dict[str, Any]:
    """
    发送请求给 DeepSeek，生成题目并返回 JSON。
    """
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)

    system_prompt = """
    你是一位专业的大学助教。请根据用户提供的课程内容，出具一套练习题。
    必须严格按照以下 JSON 格式返回，不要包含 Markdown 格式（如 ```json ... ```）：
    {
        "mcq": [
            {
                "id": "MCQ1",
                "stem": "题干内容...",
                "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
                "answer": "A",
                "explanation": "解析...",
                "evidence": ["原文中的证据句..."]
            }
        ],
        "short": [
            {
                "id": "SA1",
                "question": "简答题问题...",
                "rubric": ["评分点1", "评分点2"],
                "evidence": ["证据句..."]
            }
        ],
        "triple": [
            {
                "id": "T1",
                "concept": {"q": "概念题...", "a": "参考答案...", "evidence": ["..."]},
                "understand": {"q": "理解题...", "a": "参考答案...", "evidence": ["..."]},
                "apply": {"q": "应用题...", "a": "参考答案...", "evidence": ["..."]}
            }
        ],
        "script_1min": {
            "title": "讲解标题",
            "sections": [{"t": "0-15s", "line": "..."}]
        }
    }
    要求：
    1. 生成 5 道单选题 (mcq)。
    2. 生成 2 道简答题 (short)。
    3. 生成 1 组三层题组 (triple)。
    4. 生成 1 分钟讲解稿 (script_1min)。
    5. 难度：{difficulty}，风格：{style}。
    6. 所有题目必须基于提供的原文，严禁瞎编。
    """

    user_prompt = f"课程内容如下：\n{content}"

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",  # 如果用 SiliconFlow，改成 "deepseek-ai/DeepSeek-V3"
            messages=[
                {"role": "system", "content": system_prompt.replace("{difficulty}", difficulty).replace("{style}", style)},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            response_format={ 'type': 'json_object' }
        )
        
        result_json = response.choices[0].message.content
        return json.loads(result_json)

    except Exception as e:
        return {"mcq": [], "short": [], "triple": [], "script_1min": {}, "error": str(e)}

# ==========================================
# 3. 本地评分与错题本工具
# ==========================================

def local_grade_short(rubric: List[str], user_answer: str) -> Dict[str, Any]:
    ans = normalize_text(user_answer)
    if not ans:
        return {"score": 0, "feedback": "未作答。", "missing": rubric}

    missing = []
    hit = 0
    for item in rubric:
        ks = simple_keywords(item, topn=3)
        if any(k in ans for k in ks if k):
            hit += 1
        else:
            missing.append(item)

    if hit >= max(1, len(rubric) - 0): score = 5
    elif hit >= max(1, len(rubric) - 1): score = 4
    elif hit >= max(1, len(rubric) - 2): score = 3
    elif hit >= 1: score = 2
    else: score = 1

    feedback = f"覆盖要点 {hit}/{len(rubric)}。建议补全：{ '；'.join(missing[:2]) }"
    return {"score": score, "feedback": feedback, "missing": missing}

def wrong_key(item: Dict[str, Any]) -> str:
    return f"{item.get('type')}::{item.get('prompt')}::{ '|'.join(item.get('evidence', [])) }"

def merge_wrong(old: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    m = {wrong_key(x): x for x in old}
    for x in new:
        k = wrong_key(x)
        if k not in m:
            m[k] = x
    return list(m.values())

# ==========================================
# 4. 页面 UI 主程序
# ==========================================

st.set_page_config(page_title="AI PPT/PDF 学习小助手", layout="wide")

# 初始化 Session State
if "generated" not in st.session_state:
    st.session_state.generated = None
if "answers" not in st.session_state:
    st.session_state.answers = {}
if "wrongbook" not in st.session_state:
    st.session_state.wrongbook = []
if "short_grades" not in st.session_state:
    st.session_state.short_grades = {}
if "ppt_content" not in st.session_state:
    st.session_state.ppt_content = ""
if "messages" not in st.session_state:
    st.session_state.messages = []

st.title("AI 学习小助手 (支持 PPT & PDF)")
st.caption("基于 DeepSeek-V3 模型 | 智能出题 | 答疑解惑")

# 侧边栏
with st.sidebar:
    st.subheader("设置")
    difficulty = st.selectbox("难度", ["基础", "中等", "偏难"], index=1)
    style = st.selectbox("风格", ["启发式", "考试导向", "更口语"], index=0)
    st.divider()
    st.write("错题本数量：", len(st.session_state.wrongbook))

    if st.button("导出错题本 JSON"):
        st.download_button(
            "点击下载",
            data=json.dumps(st.session_state.wrongbook, ensure_ascii=False, indent=2),
            file_name="wrongbook.json",
            mime="application/json",
        )

    if st.button("清空错题本"):
        st.session_state.wrongbook = []
        st.success("已清空错题本。")

# 主界面分栏
col1, col2 = st.columns([1, 1.2], gap="large")

# === 左侧栏：上传和输入 ===
with col1:
    st.subheader("① 输入课程内容")
    
    # === 更新点：支持 PPTX 和 PDF ===
    uploaded_file = st.file_uploader("上传课件 (支持 PPTX / PDF)", type=["pptx", "pdf"])
    
    # 提取逻辑
    if uploaded_file:
        file_type = uploaded_file.name.split('.')[-1].lower()
        extracted_text = ""
        
        if file_type == "pptx":
            extracted_text = extract_text_from_pptx(uploaded_file)
        elif file_type == "pdf":
            extracted_text = extract_text_from_pdf(uploaded_file)
            
        if extracted_text:
            st.info(f"成功提取了 {len(extracted_text)} 个字！({file_type.upper()})")
            st.session_state.ppt_content = extracted_text
        else:
            st.warning("未能从文件中提取到文字，请检查文件是否为纯图片格式。")

    # 获取当前要显示的文字
    default_text = st.session_state.get('ppt_content', "")

    # 文本框
    content = st.text_area(
        "或者直接粘贴文本", 
        height=260, 
        value=default_text,
        placeholder="粘贴文本，或者上传上方的课件..."
    )
    
    gen_btn = st.button("一键生成题库 + 讲解稿", type="primary", use_container_width=True)

    if gen_btn:
        txt = normalize_text(content)
        # 简单截断防止费钱
        if len(txt) > 15000:
            st.warning("文本过长，已自动截取前 15000 字。")
            txt = txt[:15000]

        if len(txt) < 50:
            st.warning("文本太短了，多写点吧。")
        else:
            with st.spinner("AI 正在阅读课件并出题..."):
                try:
                    # 调用真正的 DeepSeek
                    st.session_state.generated = call_deepseek_generate(txt, difficulty, style)
                    st.session_state.answers = {}
                    st.session_state.short_grades = {}
                    st.success("生成完成！请看右侧。")
                except Exception as e:
                    st.error(f"生成失败：{e}")

# === 右侧栏：做题与答疑 ===
with col2:
    st.subheader("② 题库与学习闭环")
    g = st.session_state.generated

    if not g:
        st.write("请先在左侧输入内容并生成。")
    elif "error" in g:
        st.error(f"API 调用出错：{g['error']}")
    else:
        tab_mcq, tab_sa, tab_triple, tab_script, tab_wrong, tab_chat = st.tabs(
            ["选择题", "简答题", "三层题组", "讲解稿", "错题本", "💬 答疑助手"]
        )

        # ===== 1. 选择题 =====
        with tab_mcq:
            for q in g.get("mcq", []):
                st.markdown(f"**{q['id']}** {q['stem']}")
                opts = q["options"]
                st.radio(
                    "选项",
                    options=["A", "B", "C", "D"],
                    format_func=lambda k: f"{k}. {opts[k]}",
                    key=f"mcq_{q['id']}",
                    index=None,
                )
                with st.expander("查看答案与解析"):
                    st.write("**正确答案：**", q["answer"])
                    st.write("**解析：**", q["explanation"])
                    if q.get("evidence"):
                        st.caption(f"证据：{' '.join(q['evidence'])}")
                st.divider()

            if st.button("提交选择题"):
                wrong_items = []
                for q in g.get("mcq", []):
                    user_ans = st.session_state.get(f"mcq_{q['id']}", None)
                    if user_ans != q["answer"]:
                        wrong_items.append({
                            "id": q["id"], "type": "mcq", "prompt": q["stem"],
                            "evidence": q.get("evidence", []), "correct": q["answer"], "user": user_ans
                        })
                st.session_state.wrongbook = merge_wrong(st.session_state.wrongbook, wrong_items)
                st.success(f"已判分，新增 {len(wrong_items)} 道错题进入错题本。")

        # ===== 2. 简答题 =====
        with tab_sa:
            for q in g.get("short", []):
                st.markdown(f"**{q['id']}** {q['question']}")
                st.text_area("你的答案", key=f"sa_{q['id']}", height=100)
                if q["id"] in st.session_state.short_grades:
                    gr = st.session_state.short_grades[q["id"]]
                    st.info(f"得分：{gr['score']}/5  |  {gr['feedback']}")
                st.divider()
            
            if st.button("提交简答题评分"):
                wrong_items = []
                for q in g.get("short", []):
                    ans = st.session_state.get(f"sa_{q['id']}", "")
                    gr = local_grade_short(q["rubric"], ans)
                    st.session_state.short_grades[q["id"]] = gr
                    if gr["score"] <= 3:
                        wrong_items.append({
                            "id": q["id"], "type": "short", "prompt": q["question"],
                            "evidence": q.get("evidence", []), "correct": q.get("rubric", []), "user": ans
                        })
                st.session_state.wrongbook = merge_wrong(st.session_state.wrongbook, wrong_items)
                st.rerun()

        # ===== 3. 三层题组 =====
        with tab_triple:
            for t in g.get("triple", []):
                st.markdown(f"### {t['id']} 深度理解")
                for k, label in [("concept", "概念"), ("understand", "理解"), ("apply", "应用")]:
                    st.markdown(f"**{label}题**：{t[k]['q']}")
                    st.caption(f"参考：{t[k]['a']}")
                st.divider()

        # ===== 4. 讲解稿 =====
        with tab_script:
            s = g.get("script_1min", {})
            st.markdown(f"### {s.get('title', '讲解稿')}")
            for sec in s.get("sections", []):
                st.write(f"**[{sec['t']}]** {sec['line']}")

        # ===== 5. 错题本 =====
        with tab_wrong:
            wb = st.session_state.wrongbook
            if not wb:
                st.info("暂无错题，请先在前面做题并提交。")
            else:
                for i, item in enumerate(wb):
                    st.markdown(f"**错题 {i+1}** ({item['type']})")
                    st.write(item["prompt"])
                    st.error(f"你的回答：{item.get('user')}")
                    st.success(f"参考答案：{item.get('correct')}")
                    if st.button("我学会了，删除这题", key=f"del_{i}"):
                        st.session_state.wrongbook.pop(i)
                        st.rerun()
                    st.divider()

                if st.button("针对错题生成变式训练", type="primary"):
                    if not content.strip():
                        st.warning("请先在左侧输入原文。")
                    else:
                        with st.spinner("AI 正在分析你的错题并重新出题..."):
                            new_gen = call_deepseek_generate(normalize_text(content), difficulty, style)
                            new_gen["mcq"] = new_gen["mcq"][:3]
                            new_gen["short"] = new_gen["short"][:2]
                            st.session_state.generated = new_gen
                            st.session_state.answers = {}
                            st.success("变式题已生成！请回到‘选择题’标签页查看。")
                            st.rerun()

        # ===== 6. 答疑助手 =====
        with tab_chat:
            st.markdown("### 🤖 课件答疑助手")
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
            if q := st.chat_input("关于课件内容，你有什么不懂的？"):
                st.session_state.messages.append({"role": "user", "content": q})
                with st.chat_message("user"):
                    st.write(q)
                with st.chat_message("assistant"):
                    with st.spinner("思考中..."):
                        try:
                            client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)
                            context = st.session_state.get('ppt_content', '')[:5000]
                            resp = client.chat.completions.create(
                                model="deepseek-chat", # SiliconFlow 记得改名
                                messages=[
                                    {"role": "system", "content": f"你是一个助教。基于以下课件内容回答学生问题：\n\n{context}"},
                                    {"role": "user", "content": q}
                                ]
                            )
                            reply = resp.choices[0].message.content
                            st.write(reply)
                            st.session_state.messages.append({"role": "assistant", "content": reply})
                        except Exception as e:
                            st.error(str(e))