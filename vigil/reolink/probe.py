"""Reolink probe: model, firmware, RTSP/FLV reachability and AI-event support (FR-030).

Credentials come only from the environment (`REOLINK_USER`, `REOLINK_PASSWORD`, and the
camera's `source.host_env`), never from `cameras.yaml` (spec 6 "Security and privacy").
Every log line, exception text and repr produced here passes through `redact()`, and
stream URLs are `StreamUrl` objects whose str/repr/format are redacted, so credentials
never reach logs (NFR-031). Only `StreamUrl.secret()` returns the real URL, for handing
straight to ffmpeg or go2rtc.

`reolink-aio` (MIT, optional group `reolink`) is imported lazily inside
`ReolinkAioAdapter`; offline code and tests use any object satisfying `ProbeAdapter`.
Channel numbering: `cameras.yaml` uses 1-based NVR channels (`Preview_0N_main`), while
reolink_aio uses 0-based channel indexes; `channel_index()` converts.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Iterable
from typing import Literal, Protocol, runtime_checkable
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from vigil.models import CameraCfg

USER_ENV = "REOLINK_USER"
PASSWORD_ENV = "REOLINK_PASSWORD"  # noqa: S105 - env var name, not a secret
SECRET_ENVS = (USER_ENV, PASSWORD_ENV, "MODEL_API_KEY")
RTSP_PORT = 554
HTTP_PORT = 80
RTMP_PORT = 1935
REDACTED = "***"

StreamKind = Literal["main", "sub"]


class ReolinkUnavailable(RuntimeError):
    """reolink-aio is not installed (optional dependency group `reolink`)."""


# ---------------------------------------------------------------------------
# Redaction (NFR-031)
# ---------------------------------------------------------------------------

_URL_USERINFO = re.compile(r"(?P<scheme>\b[a-zA-Z][a-zA-Z0-9+.\-]*://)(?P<userinfo>[^/\s]*)@")
_QUERY_SECRET = re.compile(
    r"(?i)(?P<key>\b(?:user|username|usr|password|passwd|pwd|token|api_key|apikey|key)=)"
    r"(?P<val>[^&\s#\"']+)"
)
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-~+/=]+")


def _known_secrets(extra: Iterable[str] | None) -> list[str]:
    found: set[str] = set()
    for value in [*(extra or []), *(os.environ.get(name, "") for name in SECRET_ENVS)]:
        if value and len(value) >= 3:
            found.add(value)
            found.add(quote(value, safe=""))
    return sorted(found, key=len, reverse=True)


def redact(text: object, secrets: Iterable[str] | None = None) -> str:
    """Remove URL userinfo, credential query parameters, bearer tokens and known secrets.

    Known secrets are the values of `REOLINK_USER`, `REOLINK_PASSWORD` and `MODEL_API_KEY`
    in the environment plus any passed in `secrets`, raw and percent-encoded.
    """
    out = str(text)
    out = _URL_USERINFO.sub(lambda m: f"{m['scheme']}{REDACTED}:{REDACTED}@", out)
    out = _QUERY_SECRET.sub(lambda m: f"{m['key']}{REDACTED}", out)
    out = _BEARER.sub(lambda m: f"{m.group(1)}{REDACTED}", out)
    for secret in _known_secrets(secrets):
        out = out.replace(secret, REDACTED)
    return out


class RedactingFilter(logging.Filter):
    """Rewrites each record's message through `redact()` before any handler sees it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed record; keep the raw template
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


_FILTER = RedactingFilter()

# Logger filters apply only to records created on that exact logger, so every module
# logger (ours and reolink_aio's) gets the filter explicitly.
REOLINK_AIO_LOGGERS = (
    "reolink_aio",
    "reolink_aio.api",
    "reolink_aio.helpers",
    "reolink_aio.baichuan",
    "reolink_aio.baichuan.baichuan",
    "reolink_aio.baichuan.tcp_protocol",
)


def install_log_redaction(*names: str) -> None:
    for name in names:
        logger = logging.getLogger(name)
        if _FILTER not in logger.filters:
            logger.addFilter(_FILTER)


install_log_redaction(
    "vigil.reolink",
    "vigil.reolink.probe",
    "vigil.reolink.capture",
    "vigil.reolink.ai_events",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Credentials and stream URLs (spec 6 "Streams")
# ---------------------------------------------------------------------------


class Credentials:
    """Host, user and password for one camera or NVR. str/repr never show user or password."""

    __slots__ = ("host", "password", "user")

    def __init__(self, host: str, user: str, password: str) -> None:
        self.host = host
        self.user = SecretStr(user)
        self.password = SecretStr(password)

    def __repr__(self) -> str:
        return f"Credentials(host={self.host!r}, user='{REDACTED}', password='{REDACTED}')"

    __str__ = __repr__


class CredentialsError(RuntimeError):
    pass


def camera_credentials(cam: CameraCfg) -> Credentials:
    """Read the camera's host and the shared Reolink user from the environment."""
    host_env = cam.source.host_env if cam.source else None
    if not host_env:
        raise CredentialsError(f"camera {cam.id!r} has no source.host_env in cameras.yaml")
    host = os.environ.get(host_env, "").strip()
    if not host:
        raise CredentialsError(f"camera {cam.id!r}: environment variable {host_env} is not set")
    missing = [name for name in (USER_ENV, PASSWORD_ENV) if not os.environ.get(name)]
    if missing:
        raise CredentialsError(f"camera {cam.id!r}: set {' and '.join(missing)} in .env")
    return Credentials(host, os.environ[USER_ENV], os.environ[PASSWORD_ENV])


def channel_index(cam: CameraCfg) -> int:
    """0-based reolink_aio channel: config channel N (1-based, NVR) -> N-1; none -> 0."""
    ch = cam.source.channel if cam.source else None
    return 0 if ch is None else max(0, int(ch) - 1)


class StreamUrl:
    """A stream URL carrying credentials. Only `secret()` returns them."""

    __slots__ = ("_secret", "_shown", "protocol", "stream")

    def __init__(self, url: str, protocol: str, stream: str, secrets: Iterable[str]) -> None:
        self._secret = url
        self._shown = redact(url, secrets)
        self.protocol = protocol
        self.stream = stream

    def secret(self) -> str:
        return self._secret

    def __str__(self) -> str:
        return self._shown

    def __repr__(self) -> str:
        return f"StreamUrl({self._shown!r})"

    def __format__(self, spec: str) -> str:
        return format(self._shown, spec)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, StreamUrl) and other._secret == self._secret

    def __hash__(self) -> int:
        return hash(self._secret)

    def __reduce__(self):  # never pickle the secret by accident
        raise TypeError("StreamUrl cannot be pickled")


def rtsp_url(
    host: str,
    user: str,
    password: str,
    channel: int | None = None,
    stream: StreamKind = "main",
    port: int = RTSP_PORT,
) -> StreamUrl:
    """`rtsp://user:pass@IP:554/Preview_01_main`; NVR channel N gives `Preview_0N_main`.

    `channel` is the 1-based NVR channel from `cameras.yaml` (None for a standalone
    camera). User and password are percent-encoded, as reolink_aio does.
    """
    n = 1 if channel is None else int(channel)
    url = (
        f"rtsp://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
        f"/Preview_{n:02d}_{stream}"
    )
    return StreamUrl(url, "rtsp", stream, [user, password])


def flv_url(
    host: str,
    user: str,
    password: str,
    channel: int | None = None,
    stream: StreamKind = "main",
    port: int = HTTP_PORT,
    rtmp_port: int = RTMP_PORT,
) -> StreamUrl:
    """HTTP-FLV fallback (`/flv?...app=bcs&stream=channel{idx}_{stream}.bcs`).

    Mirrors reolink_aio `Host.get_flv_stream_source`, which passes the password
    unencoded in the query string; `channel` is 1-based like `rtsp_url`.
    """
    idx = 0 if channel is None else max(0, int(channel) - 1)
    url = (
        f"http://{host}:{port}/flv?port={rtmp_port}&app=bcs"
        f"&stream=channel{idx}_{stream}.bcs&user={user}&password={password}"
    )
    return StreamUrl(url, "flv", stream, [user, password])


def camera_rtsp_url(cam: CameraCfg, stream: StreamKind | None = None) -> StreamUrl:
    creds = camera_credentials(cam)
    return rtsp_url(
        creds.host,
        creds.user.get_secret_value(),
        creds.password.get_secret_value(),
        channel=cam.source.channel if cam.source else None,
        stream=stream or (cam.source.stream if cam.source else "main"),
    )


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


class HostInfo(BaseModel):
    """What the adapter learns from the camera or NVR (reolink_aio `get_host_data`)."""

    model_config = ConfigDict(extra="forbid")

    is_nvr: bool = False
    model: str | None = None
    firmware: str | None = None
    channels: list[int] = Field(default_factory=list)
    """0-based channel indexes that carry a stream."""
    channel_models: dict[int, str] = Field(default_factory=dict)
    channel_firmware: dict[int, str] = Field(default_factory=dict)
    ai_types: dict[int, list[str]] = Field(default_factory=dict)
    """reolink_aio `ai_supported_types(ch)`: "people", "vehicle", "dog_cat", ..."""
    battery: dict[int, bool] = Field(default_factory=dict)
    rtsp_port: int = RTSP_PORT
    http_port: int = HTTP_PORT
    rtmp_port: int = RTMP_PORT


class ProbeReport(BaseModel):
    """FR-030 result for one camera. Holds no credentials; `rtsp_url` is redacted."""

    model_config = ConfigDict(extra="forbid")

    camera_id: str
    host_env: str | None = None
    channel: int = 0
    """0-based reolink_aio channel index."""
    nvr: bool | None = None
    model: str | None = None
    firmware: str | None = None
    rtsp_main: bool = False
    rtsp_sub: bool = False
    flv: bool = False
    rtsp_url: str = ""
    ai_types: list[str] = Field(default_factory=list)
    ai_person: bool = False
    ai_vehicle: bool = False
    battery: bool = False
    ok: bool = False
    error: str | None = None
    notes: list[str] = Field(default_factory=list)


@runtime_checkable
class ProbeAdapter(Protocol):
    async def host_info(self, host: str, username: str, password: str) -> HostInfo: ...

    async def check_stream(self, url: StreamUrl) -> bool: ...


async def probe(cam: CameraCfg, adapter: ProbeAdapter | None = None) -> ProbeReport:
    """Probe one camera. Never raises for camera-side failures: they go in `error`."""
    host_env = cam.source.host_env if cam.source else None
    report = ProbeReport(camera_id=cam.id, host_env=host_env, channel=channel_index(cam))
    try:
        creds = camera_credentials(cam)
    except CredentialsError as err:
        report.error = redact(err)
        log.warning("probe %s: %s", cam.id, report.error)
        return report
    user, password = creds.user.get_secret_value(), creds.password.get_secret_value()
    secrets = [user, password]
    if adapter is None:
        adapter = ReolinkAioAdapter()
    try:
        info = await adapter.host_info(creds.host, user, password)
    except Exception as err:
        report.error = redact(f"{type(err).__name__}: {err}", secrets)
        log.warning("probe %s failed: %s", cam.id, report.error)
        return report

    ch = report.channel
    report.nvr = info.is_nvr
    report.model = info.channel_models.get(ch) or info.model
    report.firmware = info.channel_firmware.get(ch) or info.firmware
    report.ai_types = sorted(info.ai_types.get(ch, []))
    report.ai_person = any(t in ("people", "person") for t in report.ai_types)
    report.ai_vehicle = "vehicle" in report.ai_types
    report.battery = bool(info.battery.get(ch, False))
    if info.channels and ch not in info.channels:
        report.error = f"channel index {ch} not offered by the device (has {info.channels})"
        log.warning("probe %s: %s", cam.id, report.error)
        return report

    nvr_channel = cam.source.channel if cam.source else None
    main = rtsp_url(creds.host, user, password, nvr_channel, "main", info.rtsp_port)
    sub = rtsp_url(creds.host, user, password, nvr_channel, "sub", info.rtsp_port)
    flv = flv_url(creds.host, user, password, nvr_channel, "main", info.http_port, info.rtmp_port)
    report.rtsp_url = str(main)
    report.rtsp_main, report.rtsp_sub, report.flv = await asyncio.gather(
        _safe_check(adapter, main, secrets),
        _safe_check(adapter, sub, secrets),
        _safe_check(adapter, flv, secrets),
    )
    if not report.rtsp_main and report.flv:
        report.notes.append("RTSP main unreachable; FLV reachable, use FLV fallback (spec 6)")
    if report.battery:
        report.notes.append("battery camera: event clips only, no continuous capture (spec 6)")
    if not report.ai_person:
        report.notes.append("no on-camera person detection; motion gate only")
    report.ok = report.rtsp_main or report.flv
    if not report.ok:
        report.error = "no stream reachable (RTSP main and FLV both failed)"
    log.info(
        "probe %s: model=%s fw=%s rtsp=%s/%s flv=%s ai=%s",
        cam.id,
        report.model,
        report.firmware,
        report.rtsp_main,
        report.rtsp_sub,
        report.flv,
        ",".join(report.ai_types) or "none",
    )
    return report


async def _safe_check(adapter: ProbeAdapter, url: StreamUrl, secrets: list[str]) -> bool:
    try:
        return bool(await adapter.check_stream(url))
    except Exception as err:
        log.warning("stream check %s failed: %s", url, redact(err, secrets))
        return False


async def probe_all(
    cams: list[CameraCfg], adapter: ProbeAdapter | None = None
) -> list[ProbeReport]:
    if adapter is None:
        adapter = ReolinkAioAdapter()
    return [await probe(cam, adapter) for cam in cams]


# ---------------------------------------------------------------------------
# Real adapter (field hardware only)
# ---------------------------------------------------------------------------


def import_reolink_host():
    try:
        from reolink_aio.api import Host
    except ImportError as err:
        raise ReolinkUnavailable(
            "reolink-aio is not installed (optional group 'reolink'); "
            "blocked: field probe needs `uv sync --extra reolink` on the edge machine"
        ) from err
    install_log_redaction(*REOLINK_AIO_LOGGERS)
    return Host


class ReolinkAioAdapter:
    """Probe through reolink_aio's HTTP API, and check streams with ffprobe."""

    def __init__(self, timeout_s: float = 8.0) -> None:
        self._host_cls = import_reolink_host()
        self.timeout_s = timeout_s

    async def host_info(self, host: str, username: str, password: str) -> HostInfo:
        api = self._host_cls(host, username, password)
        try:
            await api.get_host_data()
            channels = list(api.channels)
            return HostInfo(
                is_nvr=bool(api.is_nvr),
                model=api.model,
                firmware=api.sw_version,
                channels=channels,
                channel_models={ch: api.camera_model(ch) for ch in channels},
                channel_firmware={ch: api.camera_sw_version(ch) for ch in channels},
                ai_types={ch: list(api.ai_supported_types(ch)) for ch in channels},
                battery={ch: bool(api.supported(ch, "battery")) for ch in channels},
                rtsp_port=api.rtsp_port or RTSP_PORT,
                http_port=api.port or HTTP_PORT,
                rtmp_port=api.rtmp_port or RTMP_PORT,
            )
        finally:
            await api.logout()

    async def check_stream(self, url: StreamUrl) -> bool:
        from vigil.settings import ffprobe_bin

        transport = ["-rtsp_transport", "tcp"] if url.protocol == "rtsp" else []
        cmd = [
            ffprobe_bin(),
            "-v",
            "error",
            *transport,
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "csv=p=0",
            url.secret(),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), self.timeout_s)
        except TimeoutError:
            proc.kill()
            return False
        return proc.returncode == 0 and bool(out.strip())
