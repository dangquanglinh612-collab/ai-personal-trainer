"""FastAPI factory for the Supabase-only web process."""

from datetime import date
from typing import Generic, TypeVar
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Path, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.exceptions import HTTPException

from ..backend import read_supabase_config
from ..config import PROJECT_ROOT, runtime_setting
from ..repositories.contracts import ExerciseOption, MemberDetail, MemberSummary, TrainingHistoryItem
from ..services.supabase_auth import AuthenticatedSupabase, CoachNotAllowed, SupabaseAuth
from ..services.supabase_client import SupabaseRepository
from .sessions import FastAPISession, InMemorySessionStore, SessionExpired, SessionStore


Payload = TypeVar("Payload")


class Success(BaseModel, Generic[Payload]):
    success: bool = True
    data: Payload
    error: None = None


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=1024)


class CoachIdentity(BaseModel):
    id: str


class TrainingExerciseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    exercise_name: str = Field(min_length=1, max_length=120)
    weight: str = Field(default="", max_length=40)
    sets: str = Field(default="", max_length=40)
    reps: str = Field(default="", max_length=40)
    rpe: str = Field(default="", max_length=20)
    note: str = Field(default="", max_length=500)


class TrainingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    training_date: date
    member_feedback: str = Field(default="", max_length=2000)
    coach_note: str = Field(default="", max_length=2000)
    exercises: list[TrainingExerciseInput] = Field(min_length=1, max_length=40)


class SavedTraining(BaseModel):
    session_id: int
    should_deduct_lesson: bool


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str, *, clear_cookie: bool = False):
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.clear_cookie = clear_cookie


def error_response(status: int, code: str, message: str, headers=None) -> JSONResponse:
    return JSONResponse(
        {"success": False, "data": None, "error": {"code": code, "message": message}},
        status_code=status,
        headers=headers,
    )


def create_app(
    *,
    auth: SupabaseAuth | None = None,
    store: SessionStore | None = None,
    repository_factory=SupabaseRepository,
    origin: str | None = None,
) -> FastAPI:
    if origin is None:
        origin = runtime_setting({}, "AI_COACH_WEB_ORIGIN", "http://127.0.0.1:8000")
    parsed = urlsplit(origin)
    if (
        origin != f"{parsed.scheme}://{parsed.netloc}"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.scheme not in ("http", "https")
        or (parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"))
    ):
        raise ValueError("AI_COACH_WEB_ORIGIN must be an HTTPS origin or a loopback HTTP origin.")
    if auth is None:
        settings, allowed = read_supabase_config({})
        auth = SupabaseAuth(settings, allowed)
    sessions = FastAPISession(auth, store if store is not None else InMemorySessionStore())
    secure = parsed.scheme == "https"
    cookie_name = "__Host-ai_coach_session" if secure else "ai_coach_dev_session"
    cookie_options = {"httponly": True, "secure": secure, "samesite": "lax", "path": "/"}
    app = FastAPI(title="AI Coach OS API", version="1")

    @app.middleware("http")
    async def safe_response(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            response = error_response(500, "INTERNAL_ERROR", "暂时无法处理该请求")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(APIError)
    async def handle_api_error(request: Request, error: APIError):
        response = error_response(error.status, error.code, error.message)
        if error.clear_cookie:
            response.delete_cookie(cookie_name, **cookie_options)
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, error: RequestValidationError):
        return error_response(422, "INVALID_REQUEST", "请求参数无效")

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, error: HTTPException):
        messages = {404: "接口不存在", 405: "请求方法不受支持"}
        return error_response(error.status_code, f"HTTP_{error.status_code}",
                              messages.get(error.status_code, "请求无法完成"), error.headers)

    def reject_query(request: Request) -> None:
        if request.query_params:
            raise APIError(422, "INVALID_QUERY", "此接口不接收查询参数")

    def require_same_origin(request: Request) -> None:
        if (
            request.headers.get("origin") != origin
            or request.headers.get("x-ai-coach-request") != "1"
        ):
            raise APIError(403, "ORIGIN_REJECTED", "请求来源无效")
        reject_query(request)

    def require_session(request: Request) -> AuthenticatedSupabase:
        try:
            authenticated = sessions.restore(request.cookies.get(cookie_name)).authenticated
        except CoachNotAllowed:
            raise APIError(403, "COACH_NOT_ALLOWED", "此账号未获准进入教练工作台", clear_cookie=True) from None
        except (SessionExpired, ValueError):
            raise APIError(401, "UNAUTHORIZED", "请先登录", clear_cookie=True) from None
        reject_query(request)
        return authenticated

    def get_member(repository, coach, member_id: int) -> MemberDetail:
        member = repository.get_member(coach, member_id)
        if member is None:
            raise APIError(404, "MEMBER_NOT_FOUND", "未找到该会员")
        return member

    @app.post("/api/v1/auth/login", response_model=Success[CoachIdentity],
              dependencies=[Depends(require_same_origin)])
    def login(request: Request, response: Response, credentials: LoginInput):
        try:
            session_id, result = sessions.login(
                credentials.email, credentials.password.get_secret_value(),
                request.cookies.get(cookie_name),
            )
        except CoachNotAllowed:
            raise APIError(403, "COACH_NOT_ALLOWED", "此账号未获准进入教练工作台") from None
        except ValueError:
            raise APIError(401, "LOGIN_FAILED", "登录失败，请检查邮箱和密码后重试") from None
        response.set_cookie(cookie_name, session_id, **cookie_options)
        return Success(data=CoachIdentity(id=result.authenticated.coach.coach_id))

    @app.post("/api/v1/auth/logout", response_model=Success[None],
              dependencies=[Depends(require_same_origin)])
    def logout(request: Request, response: Response):
        sessions.logout(request.cookies.get(cookie_name))
        response.delete_cookie(cookie_name, **cookie_options)
        return Success(data=None)

    @app.get("/api/v1/auth/me", response_model=Success[CoachIdentity])
    def me(authenticated: AuthenticatedSupabase = Depends(require_session)):
        return Success(data=CoachIdentity(id=authenticated.coach.coach_id))

    @app.get("/api/v1/members", response_model=Success[list[MemberSummary]])
    def members(authenticated: AuthenticatedSupabase = Depends(require_session)):
        return Success(data=repository_factory(authenticated).list_members(authenticated.coach))

    @app.get("/api/v1/members/{member_id}", response_model=Success[MemberDetail])
    def member_detail(
        member_id: int = Path(gt=0, lt=2**63),
        authenticated: AuthenticatedSupabase = Depends(require_session),
    ):
        return Success(data=get_member(repository_factory(authenticated), authenticated.coach, member_id))

    @app.get("/api/v1/exercises", response_model=Success[list[ExerciseOption]])
    def exercises(authenticated: AuthenticatedSupabase = Depends(require_session)):
        return Success(data=repository_factory(authenticated).list_exercises(authenticated.coach))

    @app.get("/api/v1/members/{member_id}/training-sessions",
             response_model=Success[list[TrainingHistoryItem]])
    def training_sessions(
        member_id: int = Path(gt=0, lt=2**63),
        authenticated: AuthenticatedSupabase = Depends(require_session),
    ):
        repository = repository_factory(authenticated)
        coach = authenticated.coach
        get_member(repository, coach, member_id)
        return Success(data=repository.list_training_history(coach, member_id))

    @app.post("/api/v1/members/{member_id}/training-sessions", status_code=201,
              response_model=Success[SavedTraining], dependencies=[Depends(require_same_origin)])
    def add_training(
        entry: TrainingInput, member_id: int = Path(gt=0, lt=2**63),
        authenticated: AuthenticatedSupabase = Depends(require_session),
    ):
        repository = repository_factory(authenticated)
        get_member(repository, authenticated.coach, member_id)
        result = repository.save_training_session(
            member_id, entry.training_date, entry.member_feedback, entry.coach_note, "",
            [exercise.model_dump() for exercise in entry.exercises],
        )
        return Success(data=SavedTraining.model_validate(result))

    prototype = PROJECT_ROOT / "prototype"

    @app.get("/app/", include_in_schema=False)
    def coach_workspace():
        return FileResponse(prototype / "ai_coach_os_coach_final.html", headers={
            "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                       "style-src 'self' 'unsafe-inline'; object-src 'none'; "
                                       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
            "Referrer-Policy": "same-origin",
            "X-Content-Type-Options": "nosniff",
        })

    app.mount("/app/assets", StaticFiles(directory=prototype / "connected"), name="connected-assets")

    return app
