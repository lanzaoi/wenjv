import streamlit as st
import requests
from frontend.utils import navigate_to, save_token_to_storage, clear_token_from_storage
from frontend.config import settings


def login_user(email, password):
    """Login a user using JWT authentication with email only"""
    try:
        # FastAPI-Users expects email in the "username" field
        login_data = {
            "username": email,  # This is the email field for FastAPI-Users
            "password": password
        }

        response = requests.post(
            f"{settings.API_URL}/auth/jwt/login",
            data=login_data  # Use data, not json for form data
        )

        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token")

            if token:
                # Save token to session state
                st.session_state.token = token
                st.session_state.username = email  # Just use email as the identifier
                st.session_state.authenticated = True

                # Save token to browser storage

                save_token_to_storage(token, email)

                return True, "登录成功"

            return False, "收到无效的鉴权 Token"

        return False, f"登录失败: {response.text}"
    except Exception as e:
        return False, f"登录出错: {str(e)}"


def register_user(email, password):
    """Register a new user with just email and password"""
    if not settings.ALLOW_AUTO_USER_REGISTER:
        return False, "系统当前不允许自行注册，请联系管理员"
    try:
        response = requests.post(
            f"{settings.API_URL}/auth/register",
            json={"email": email, "password": password}  # No username
        )

        if response.status_code == 201:
            return True, "注册成功"

        return False, f"注册失败: {response.text}"
    except Exception as e:
        return False, f"注册出错: {str(e)}"


def logout_user():
    """Logout user by clearing the token"""
    # Clear token from browser storage

    # Reset session state
    st.session_state.token = None
    st.session_state.username = None  # This clears the email
    st.session_state.authenticated = False
    st.session_state.current_page = "login"
    st.session_state.messages = []

    clear_token_from_storage()


def show_login_page():
    st.title("登录")

    with st.form("login_form"):
        email = st.text_input("邮箱")
        password = st.text_input("密码", type="password")
        submit = st.form_submit_button("登录")

        if submit:
            if email and password:
                success, message = login_user(email, password)
                if success:
                    st.success(message)
                    navigate_to("rag")
                else:
                    st.error(message)
            else:
                st.warning("请输入邮箱和密码")

    st.markdown("---")
    st.write("还没有账号？")
    if st.button("立即注册"):
        navigate_to("register")


def show_register_page():
    st.title("注册")

    with st.form("register_form"):
        email = st.text_input("邮箱")
        password = st.text_input("密码", type="password")
        confirm_password = st.text_input("确认密码", type="password")
        submit = st.form_submit_button("注册")

        if submit:
            if not (email and password and confirm_password):
                st.warning("请填写所有字段")
            elif password != confirm_password:
                st.warning("两次输入的密码不一致")
            else:
                success, message = register_user(email, password)
                if success:
                    st.success(message)
                    navigate_to("login")
                else:
                    st.error(message)

    st.markdown("---")
    st.write("已经有账号了？")
    if st.button("返回登录"):
        navigate_to("login")
