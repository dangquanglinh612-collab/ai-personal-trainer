"""Streamlit style injection and visual asset helpers."""

from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

from ai_coach_os.config import PROJECT_ROOT

def image_to_base64(image_path):
    path = Path(image_path)

    if not path.exists():
        return ""

    return base64.b64encode(path.read_bytes()).decode()


# =========================
# CSS
# =========================

def inject_css():
    st.markdown("""
    <style>
    :root {
        --primary: #2D82B8;
        --primary-dark: #025B93;
        --primary-soft: #BEE6FF;
        --primary-softer: #EDF7FC;
        --page-bg: #F6FAFD;
        --card-bg: #FFFFFF;
        --card-muted: #FAFCFD;
        --text-main: #0B2530;
        --text-body: #263B43;
        --text-soft: #536B75;
        --border: rgba(135, 192, 202, 0.45);
        --border-strong: #87C0CA;
        --notice-bg: #EAF6FA;
        --hero-start: #D7E8EA;
        --hero-end: #F8FCFD;
        --shadow-soft: 0 6px 18px rgba(11, 37, 48, 0.055);
        --shadow-hover: 0 8px 22px rgba(11, 37, 48, 0.08);
        --radius-main: 16px;
        --radius-card: 12px;
        --radius-control: 10px;
    }

    .stApp {
        background:
            radial-gradient(circle at 12% 8%, rgba(190, 230, 255, 0.24) 0%, transparent 28%),
            linear-gradient(180deg, #FAFCFE 0%, var(--page-bg) 52%, #F1F7FA 100%);
        color: var(--text-body);
    }

    .block-container {
        max-width: 1040px;
        padding-top: 3rem;
        padding-bottom: 4rem;
    }

    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #EEF8FA 0%, #F8FCFD 100%);
        border-right: 1px solid var(--border);
    }

    html, body, [class*="css"] {
        color: var(--text-body);
    }

    h1, h2, h3 {
        color: var(--text-main);
        letter-spacing: 0;
    }

    p, li, label, span {
        color: inherit;
    }

    div[data-testid="stMarkdownContainer"] p {
        font-size: 16px;
        line-height: 1.75;
    }

    .page-header {
        padding: 6px 2px 20px 2px;
    }

    .page-eyebrow {
        color: var(--primary-dark);
        font-size: 14px;
        font-weight: 600;
        margin-bottom: 8px;
    }

    .page-title {
        color: var(--text-main);
        font-size: 32px;
        font-weight: 700;
        line-height: 1.2;
        margin-bottom: 8px;
        letter-spacing: 0;
    }

    .page-subtitle {
        color: var(--text-soft);
        font-size: 16px;
        line-height: 1.7;
        max-width: 760px;
    }

    .soft-divider {
        height: 1px;
        background: var(--border);
        margin: 24px 0 22px 0;
    }

    .member-card {
        border: 1px solid var(--border);
        border-radius: var(--radius-main);
        padding: 20px 22px;
        margin-bottom: 14px;
        background: var(--card-bg);
        box-shadow: var(--shadow-soft);
        transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
    }

    .member-card:hover {
        border-color: var(--border-strong);
        box-shadow: var(--shadow-hover);
        transform: translateY(-1px);
    }

    .member-name {
        font-size: 21px;
        font-weight: 700;
        color: var(--text-main);
        margin-bottom: 8px;
    }

    .member-status {
        color: var(--text-body);
        font-size: 15px;
        line-height: 1.7;
        margin-bottom: 2px;
    }

    .member-meta {
        color: var(--text-soft);
        font-size: 15px;
        line-height: 1.7;
    }

    .badge {
        display: inline-block;
        padding: 4px 9px;
        border-radius: 10px;
        font-size: 13px;
        font-weight: 600;
        margin-bottom: 10px;
    }

    .badge-blue {
        color: #176B7C;
        background: #E7F5F8;
        border: 1px solid #B7DCE4;
    }

    .badge-green {
        color: #2F6F5F;
        background: #EDF8F3;
        border: 1px solid #BFE3D2;
    }

    .badge-yellow {
        color: #7A5B21;
        background: #FFF8E7;
        border: 1px solid #EAD7A7;
    }

    .badge-red {
        color: #8B3A3A;
        background: #FFF1F1;
        border: 1px solid #E9C4C4;
    }

    .badge-purple {
        color: #66517A;
        background: #F6F1FA;
        border: 1px solid #DED2E8;
    }

    .hero-card {
        border-radius: var(--radius-main);
        padding: 30px 32px;
        margin: 8px 0 22px 0;
        background: linear-gradient(105deg, var(--hero-start) 0%, #E9F3F4 52%, var(--hero-end) 100%);
        border: 1px solid var(--border);
        box-shadow: var(--shadow-soft);
    }

    .hero-card .page-eyebrow {
        color: var(--primary-dark);
    }

    .hero-name {
        font-size: 36px;
        font-weight: 700;
        color: var(--text-main);
        margin-bottom: 16px;
        letter-spacing: 0;
    }

    .hero-desc {
        font-size: 16px;
        color: var(--text-body);
        line-height: 1.8;
        max-width: 720px;
    }

    .hero-info-line {
        color: var(--text-body);
        font-size: 15px;
        line-height: 1.9;
        max-width: 760px;
    }

    .notice-card {
        background: var(--notice-bg);
        border: 1px solid var(--border-strong);
        color: var(--text-main);
        border-radius: var(--radius-card);
        padding: 16px 20px;
        font-size: 15px;
        font-weight: 600;
        margin: 18px 0 10px 0;
        box-shadow: none;
    }

    .section-card {
        border: 1px solid var(--border);
        border-radius: var(--radius-main);
        padding: 22px 24px;
        margin-bottom: 18px;
        background: var(--card-bg);
        box-shadow: var(--shadow-soft);
    }

    .section-line {
        color: var(--text-soft);
        font-size: 15px;
        line-height: 1.9;
    }

    .action-card {
        border: 1px solid var(--border-strong);
        border-radius: var(--radius-main);
        padding: 22px 24px;
        background: var(--card-bg);
        box-shadow: var(--shadow-soft);
        margin-bottom: 14px;
        min-height: 126px;
    }

    .action-title {
        font-size: 18px;
        font-weight: 700;
        color: var(--text-main);
        margin-bottom: 10px;
    }

    .action-sub {
        font-size: 15px;
        color: var(--text-soft);
        line-height: 1.75;
    }

    div.stButton > button {
        border-radius: var(--radius-control);
        border: 1px solid var(--border-strong);
        min-height: 44px;
        font-size: 15px;
        font-weight: 600;
        color: #2B5964;
        background: #FFFFFF;
        box-shadow: none;
        transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease, transform 0.12s ease;
    }

    div.stButton > button[kind="primary"] {
        background: var(--primary-dark);
        color: #FFFFFF;
        border-color: var(--primary-dark);
    }

    div.stButton > button:hover {
        background: var(--primary-softer);
        border-color: var(--primary);
        color: var(--primary-dark);
    }

    div.stButton > button[kind="primary"]:hover {
        background: #014B79;
        color: #FFFFFF;
        border-color: #014B79;
    }

    div.stButton > button:active {
        transform: translateY(1px);
    }

    div.stButton > button:focus-visible {
        outline: 3px solid rgba(47, 143, 163, 0.24);
        outline-offset: 2px;
    }

    div[data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid var(--border);
        border-radius: var(--radius-card);
        padding: 16px 18px;
        box-shadow: none;
    }

    div[data-testid="stMetric"] label,
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] {
        color: var(--text-soft);
        font-size: 14px;
    }

    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: var(--text-main);
        font-size: 24px;
        font-weight: 700;
    }

    div[data-testid="stTextInput"] div[data-baseweb="input"],
    div[data-testid="stNumberInput"] div[data-baseweb="input"],
    div[data-testid="stDateInput"] div[data-baseweb="input"],
    div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
    div[data-testid="stTextInputRootElement"],
    div[data-testid="stNumberInputContainer"],
    div[data-testid="stDateInputField"],
    div[data-testid="stTextAreaRootElement"],
    div[data-testid="stSelectbox"] button[role="combobox"],
    div[data-testid="stTextArea"] textarea {
        width: 100%;
        min-height: 46px;
        background: rgba(255, 255, 255, 0.96) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius-control) !important;
        color: var(--text-main) !important;
        font-size: 16px !important;
        box-shadow: none !important;
    }

    div[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within,
    div[data-testid="stNumberInput"] div[data-baseweb="input"]:focus-within,
    div[data-testid="stDateInput"] div[data-baseweb="input"]:focus-within,
    div[data-testid="stSelectbox"] div[data-baseweb="select"] > div:focus-within,
    div[data-testid="stTextInputRootElement"]:focus-within,
    div[data-testid="stNumberInputContainer"]:focus-within,
    div[data-testid="stDateInputField"]:focus-within,
    div[data-testid="stTextAreaRootElement"]:focus-within,
    div[data-testid="stSelectbox"] button[role="combobox"]:focus,
    div[data-testid="stTextArea"] textarea:focus {
        border-color: var(--primary) !important;
        box-shadow: 0 0 0 3px rgba(45, 130, 184, 0.14) !important;
        outline: none !important;
    }

    div[data-testid="stTextInput"] input,
    div[data-testid="stNumberInput"] input,
    div[data-testid="stDateInput"] input {
        min-height: 44px;
        background: transparent !important;
        border: 0 !important;
        border-radius: inherit !important;
        color: var(--text-main) !important;
        font-size: 16px !important;
        box-shadow: none !important;
        outline: none !important;
    }

    div[data-testid="stTextAreaRootElement"] textarea {
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
        outline: none !important;
    }

    div[data-testid="stTextInput"] div[data-baseweb="input"] > button {
        flex: 0 0 42px;
        width: 42px;
        min-width: 42px;
        height: 42px;
        margin-right: 1px;
        padding: 0;
        border: 0;
        border-radius: 8px;
        background: transparent;
        box-shadow: none;
    }

    div[data-testid="stTextInput"] div[data-baseweb="input"] > button:hover {
        background: var(--primary-softer);
    }

    div[class*="st-key-training_"][class*="_count"] {
        width: 100%;
        max-width: 210px;
    }

    div[data-testid="stTextInput"] label,
    div[data-testid="stNumberInput"] label,
    div[data-testid="stTextArea"] label,
    div[data-testid="stSelectbox"] label {
        color: var(--text-main);
        font-size: 15px;
        font-weight: 600;
    }

    div[data-testid="stExpander"] {
        border: 1px solid var(--border);
        border-radius: var(--radius-main);
        background: rgba(255, 255, 255, 0.78);
        box-shadow: none;
    }

    div[data-testid="stLayoutWrapper"] > div[data-testid="stVerticalBlock"] {
        margin-bottom: 14px;
        background: rgba(255, 255, 255, 0.90);
        border-color: rgba(135, 192, 202, 0.52) !important;
        border-radius: var(--radius-main) !important;
        box-shadow: 0 4px 14px rgba(11, 37, 48, 0.04);
    }

    div[data-testid="stAlert"] {
        border-radius: var(--radius-card);
        border: 1px solid var(--border);
        box-shadow: none;
    }

    div[role="radiogroup"] label {
        font-size: 15px;
    }

    @media (max-width: 768px) {
        .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
            padding-top: 2.5rem;
        }

        .page-title {
            font-size: 28px;
        }

        .hero-name {
            font-size: 30px;
        }

        .hero-card,
        .member-card,
        .action-card,
        .section-card {
            padding: 18px 20px;
        }
    }
    </style>
    """, unsafe_allow_html=True)


def inject_login_css():
    login_bg_path = PROJECT_ROOT / "assets" / "login_bg.png"
    login_bg_mime = "image/png"
 
    login_bg_base64 = image_to_base64(login_bg_path)
    login_bg_image = (
        f"url('data:{login_bg_mime};base64,{login_bg_base64}')"
        if login_bg_base64
        else "linear-gradient(135deg, #F7FBFC 0%, #EEF7F8 100%)"
    )

    st.markdown(
        f"""
        <style>
        .stApp {{
            position: relative;
            background: #F2FAFB;
            overflow: hidden;
        }}

        .stApp::before {{
            content: "";
            position: fixed;
            inset: 0;
            background-image: {login_bg_image};
            background-size: cover;
            background-position: center;
            opacity: 0.62;
            filter: blur(0.6px) saturate(1.08) contrast(1.03);
            transform: scale(1.005);
            z-index: 0;
            pointer-events: none;
        }}

        .stApp::after {{
            content: "";
            position: fixed;
            inset: 0;
            background:
                linear-gradient(
                    120deg,
                    rgba(247, 251, 252, 0.38) 0%,
                    rgba(214, 232, 232, 0.28) 45%,
                    rgba(135, 192, 202, 0.18) 100%
                );
            z-index: 0;
            pointer-events: none;
        }}

        .stApp > * {{
            position: relative;
            z-index: 1;
        }}

        div[data-testid="stAppViewContainer"] {{
            position: relative;
            background: transparent;
            z-index: 1;
        }}

        main,
        div[data-testid="stAppViewContainer"] > .main,
        div[data-testid="stMain"],
        section.main {{
            position: relative;
            z-index: 1;
        }}

        .stApp > header {{
            background: transparent;
            z-index: 2;
        }}

        .block-container {{
            max-width: 760px;
            padding-top: 7rem;
            position: relative;
            z-index: 1;
        }}

        .login-brand-card {{
            border-radius: 30px;
            padding: 36px 38px;
            margin-bottom: 22px;
            background: rgba(255, 255, 255, 0.78);
            border: 1px solid rgba(255, 255, 255, 0.72);
            box-shadow: 0 28px 70px rgba(81, 135, 145, 0.16);
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
        }}

        .login-eyebrow {{
            color: #0F59A4;
            font-size: 14px;
            font-weight: 900;
            margin-bottom: 14px;
            letter-spacing: 0.04em;
        }}

        .login-title {{
            color: #06141B;
            font-size: 46px;
            font-weight: 950;
            line-height: 1.05;
            margin-bottom: 16px;
            letter-spacing: -0.05em;
        }}

        .login-desc {{
            color: #374151;
            font-size: 16px;
            line-height: 1.85;
            max-width: 620px;
        }}

        div[data-testid="stForm"] {{
            background: rgba(255, 255, 255, 0.80);
            border: 1px solid rgba(255, 255, 255, 0.78);
            border-radius: 26px;
            padding: 26px 28px;
            box-shadow: 0 24px 60px rgba(81, 135, 145, 0.14);
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
        }}

        div[data-testid="stTextInput"] label {{
            color: #06141B;
            font-weight: 800;
        }}

        div[data-testid="stTextInput"] input {{
            background: transparent !important;
            border: 0 !important;
            border-radius: inherit;
            min-height: 48px;
            color: #06141B;
            box-shadow: none !important;
        }}

        div[data-testid="stTextInput"] div[data-baseweb="input"] {{
            width: 100%;
            min-height: 50px;
            background: rgba(255, 255, 255, 0.96);
            border: 1px solid rgba(135, 192, 202, 0.62);
            border-radius: 12px;
            box-shadow: none;
        }}

        div[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within {{
            border-color: #2D82B8;
            box-shadow: 0 0 0 3px rgba(45, 130, 184, 0.14);
        }}

        div[data-testid="stTextInput"] div[data-baseweb="input"] > button {{
            flex: 0 0 44px;
            width: 44px;
            min-width: 44px;
            height: 44px;
            margin-right: 2px;
            padding: 0;
            border: 0;
            border-radius: 9px;
            background: transparent;
            box-shadow: none;
        }}

        div.stButton > button {{
            border-radius: 15px;
            min-height: 48px;
            font-weight: 900;
            background: #FFFFFF;
            color: #06141B;
            border: 1px solid #B0D5DF;
        }}

        div.stButton > button:hover {{
            background: #D6E8E8;
            border-color: #87C0CA;
            color: #06141B;
        }}

        .stAlert {{
            background: rgba(255, 255, 255, 0.76);
            color: #06141B;
            border-radius: 18px;
            border: 1px solid rgba(176, 213, 223, 0.72);
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
        }}

        .stAlert p {{
            color: #06141B;
        }}

        @media (max-width: 768px) {{
            .block-container {{
                padding-top: 4rem;
                padding-left: 1.2rem;
                padding-right: 1.2rem;
            }}

            .login-title {{
                font-size: 38px;
            }}

            .login-brand-card {{
                padding: 30px 28px;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True
    )


